const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function loadApp({ initialStorage = {}, handleRequest } = {}) {
  const storage = new Map(Object.entries(initialStorage));
  const calls = { login: 0, requests: [], relaunches: [] };
  let app;

  const wx = {
    getSystemInfoSync: () => ({ platform: 'devtools' }),
    getAccountInfoSync: () => ({ miniProgram: { envVersion: 'develop' } }),
    getStorageSync: key => storage.get(key),
    setStorageSync: (key, value) => storage.set(key, value),
    removeStorageSync: key => storage.delete(key),
    login(options) {
      calls.login += 1;
      queueMicrotask(() => options.success({ code: 'wx-one-time-code' }));
    },
    request(options) {
      calls.requests.push(options);
      queueMicrotask(() => handleRequest(options));
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
    console,
    setTimeout,
    clearTimeout,
    wx,
  });

  return { app, calls, storage };
}

async function testFirstLaunchAutomaticallyLogsIn() {
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
  const user = await fixture.app.globalData.sessionRestorePromise;

  assert.equal(user.id, 7);
  assert.equal(fixture.calls.login, 1);
  assert.equal(requestOptions.url, 'http://127.0.0.1:8000/api/auth/login');
  assert.equal(requestOptions.data.code, 'wx-one-time-code');
  assert.equal(fixture.app.globalData.accessToken, 'app-token');
  assert.equal(fixture.app.globalData.isNewUser, true);
  assert.equal(fixture.app.globalData.profileRequired, true);
  assert.equal(fixture.storage.get('accessToken'), 'app-token');
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

async function testExpiredCachedSessionAutomaticallyLogsInAgain() {
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
  const user = await fixture.app.globalData.sessionRestorePromise;

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
  assert.equal(fixture.calls.requests.length, 0);
}

(async () => {
  await testFirstLaunchAutomaticallyLogsIn();
  await testCachedSessionIsVerifiedWithoutWxLogin();
  await testExpiredCachedSessionAutomaticallyLogsInAgain();
  await testLogoutRequiresManualLogin();
  console.log('miniapp auth tests passed');
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
