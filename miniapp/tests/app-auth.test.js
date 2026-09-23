const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function loadApp({ initialStorage = {}, handleRequest, platform = 'devtools', envVersion = 'develop' } = {}) {
  const storage = new Map(Object.entries(initialStorage));
  const calls = { login: 0, requests: [], relaunches: [], errors: [] };
  let app;

  const wx = {
    getDeviceInfo: () => ({ platform }),
    getSystemInfoSync: () => ({ platform }),
    getAccountInfoSync: () => ({ miniProgram: { envVersion } }),
    getStorageSync: key => storage.get(key),
    setStorageSync: (key, value) => storage.set(key, value),
    removeStorageSync: key => storage.delete(key),
    login(options) {
      calls.login += 1;
      queueMicrotask(() => options.success({ code: 'wx-one-time-code' }));
    },
    request(options) {
      calls.requests.push(options);
      queueMicrotask(() => {
        if (options.url.endsWith('/api/auth/logout')) {
          options.complete && options.complete({ statusCode: 200 });
          return;
        }
        handleRequest(options);
      });
    },
    reLaunch(options) {
      calls.relaunches.push(options.url);
    },
  };

  const source = fs.readFileSync(path.join(__dirname, '..', 'app.js'), 'utf8');
  vm.runInNewContext(source, {
    App(definition) { app = definition; },
    Error,
    Promise,
    console: {
      log: console.log,
      warn: console.warn,
      error: (...args) => calls.errors.push(args),
    },
    setTimeout,
    clearTimeout,
    wx,
  });

  return { app, calls, storage };
}

async function testFirstLaunchWaitsForOneTapLogin() {
  let requestOptions;
  const fixture = loadApp({
    handleRequest(options) {
      requestOptions = options;
      options.success({
        statusCode: 200,
        data: {
          user: { id: 7, nickname: '微信用户', avatar: '' },
          is_new: true,
          access_token: 'app-token',
        },
      });
    },
  });

  fixture.app.onLaunch();
  const restoredUser = await fixture.app.globalData.sessionRestorePromise;

  assert.equal(restoredUser, null);
  assert.equal(fixture.calls.login, 0);
  assert.equal(fixture.calls.requests.length, 0);

  const user = await fixture.app.wxLogin();

  assert.equal(user.id, 7);
  assert.equal(fixture.calls.login, 1);
  assert.equal(requestOptions.url, 'https://api.quizapp.chat/api/auth/login');
  assert.equal(requestOptions.data.code, 'wx-one-time-code');
  assert.equal(requestOptions.timeout, 15000);
  assert.equal(fixture.app.globalData.accessToken, 'app-token');
  assert.equal(fixture.app.globalData.isNewUser, true);
  assert.equal(fixture.app.globalData.profileRequired, false);
  assert.equal(fixture.storage.get('accessToken'), 'app-token');
}

async function testDevelopEnvironmentUsesProductionHttps() {
  const fixture = loadApp();

  fixture.app.onLaunch();
  await fixture.app.globalData.sessionRestorePromise;

  assert.equal(fixture.app.globalData.baseUrl, 'https://api.quizapp.chat');
  assert.equal(fixture.calls.requests.length, 0);
}

async function testLoginReportsRequestDomainFailure() {
  const fixture = loadApp({
    platform: 'android',
    handleRequest(options) {
      options.fail({
        errMsg: 'request:fail url not in domain list',
        errno: 600001,
      });
    },
  });

  fixture.app.onLaunch();
  await fixture.app.globalData.sessionRestorePromise;

  await assert.rejects(
    fixture.app.wxLogin(),
    /API 域名未加入微信 request 合法域名/,
  );
  assert.equal(fixture.calls.requests[0].timeout, 15000);
  assert.equal(fixture.calls.errors.length, 1);
  assert.equal(fixture.calls.errors[0][1].errno, 600001);
}

async function testLoginReportsAbortedConnection() {
  const fixture = loadApp({
    platform: 'android',
    handleRequest(options) {
      options.fail({
        errMsg: 'request:fail net::ERR_CONNECTION_CLOSED',
        errno: -100,
      });
    },
  });

  fixture.app.onLaunch();
  await fixture.app.globalData.sessionRestorePromise;

  await assert.rejects(
    fixture.app.wxLogin(),
    /服务器连接被中止，请检查 HTTPS\/TLS 配置/,
  );
}

async function testCachedSessionIsVerifiedWithoutWxLogin() {
  const fixture = loadApp({
    initialStorage: {
      userInfo: { id: 3, nickname: '旧昵称', avatar: '' },
      accessToken: 'cached-token',
    },
    handleRequest(options) {
      options.success({
        statusCode: 200,
        data: { id: 3, nickname: '服务端昵称', avatar: '', is_admin: false },
      });
    },
  });

  fixture.app.onLaunch();
  const user = await fixture.app.globalData.sessionRestorePromise;

  assert.equal(user.nickname, '服务端昵称');
  assert.equal(fixture.app.globalData.profileRequired, false);
  assert.equal(fixture.calls.login, 0);
  assert.equal(fixture.calls.requests.length, 1);
  assert.equal(fixture.calls.requests[0].header.Authorization, 'Bearer cached-token');
}

async function testExpiredCachedSessionWaitsForOneTapLogin() {
  const fixture = loadApp({
    initialStorage: {
      userInfo: { id: 3, nickname: '旧昵称', avatar: '' },
      accessToken: 'expired-token',
    },
    handleRequest(options) {
      if (options.url.endsWith('/api/auth/me')) {
        options.success({ statusCode: 401, data: { detail: 'expired' } });
        return;
      }
      options.success({
        statusCode: 200,
        data: {
          user: { id: 3, nickname: '新会话', avatar: '' },
          is_new: false,
          access_token: 'renewed-token',
        },
      });
    },
  });

  fixture.app.onLaunch();
  const restoredUser = await fixture.app.globalData.sessionRestorePromise;

  assert.equal(restoredUser, null);
  assert.equal(fixture.calls.login, 0);
  assert.equal(fixture.calls.requests.length, 1);

  const user = await fixture.app.wxLogin();

  assert.equal(user.nickname, '新会话');
  assert.equal(fixture.calls.login, 1);
  assert.equal(fixture.calls.requests.length, 2);
  assert.equal(fixture.storage.get('accessToken'), 'renewed-token');
}

async function testLogoutRequiresManualLogin() {
  const fixture = loadApp({
    handleRequest() {
      throw new Error('logout launch must not request a new session');
    },
  });
  fixture.app._setSession({ id: 9, nickname: '用户' }, 'token');
  fixture.app.logout();

  assert.equal(fixture.storage.get('manualLoginRequired'), true);
  assert.equal(fixture.calls.relaunches[0], '/pages/login/login');

  fixture.app.onLaunch();
  const user = await fixture.app.globalData.sessionRestorePromise;
  assert.equal(user, null);
  assert.equal(fixture.calls.login, 0);
  assert.equal(fixture.calls.requests.length, 1);
  assert.equal(fixture.calls.requests[0].url, 'https://api.quizapp.chat/api/auth/logout');
}

(async () => {
  await testFirstLaunchWaitsForOneTapLogin();
  await testDevelopEnvironmentUsesProductionHttps();
  await testLoginReportsRequestDomainFailure();
  await testLoginReportsAbortedConnection();
  await testCachedSessionIsVerifiedWithoutWxLogin();
  await testExpiredCachedSessionWaitsForOneTapLogin();
  await testLogoutRequiresManualLogin();
  console.log('miniapp auth tests passed');
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
