const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const GUEST_USER = { id: 50, nickname: '游客', avatar: '', is_admin: false, is_guest: true };
const REAL_USER = { id: 7, nickname: '微信用户', avatar: '', is_admin: false, is_guest: false };

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

function respondGuest(options) {
  options.success({
    statusCode: 200,
    data: { user: GUEST_USER, is_new: true, access_token: 'guest-token' },
  });
}

function respondRealLogin(options) {
  options.success({
    statusCode: 200,
    data: { user: REAL_USER, is_new: true, access_token: 'app-token' },
  });
}

async function testFirstLaunchCreatesSilentGuestSession() {
  let guestRequest;
  let loginRequest;
  const fixture = loadApp({
    handleRequest(options) {
      if (options.url.endsWith('/api/auth/guest')) {
        guestRequest = options;
        respondGuest(options);
        return;
      }
      if (options.url.endsWith('/api/auth/login')) {
        loginRequest = options;
        respondRealLogin(options);
        return;
      }
      options.success({ statusCode: 404, data: {} });
    },
  });

  fixture.app.onLaunch();
  const restoredUser = await fixture.app.globalData.sessionRestorePromise;

  // 首次启动：静默创建游客会话，不弹授权、不调用 wx.login
  assert.equal(restoredUser.id, GUEST_USER.id);
  assert.equal(fixture.calls.login, 0);
  assert.equal(guestRequest.url, 'https://api.quizapp.chat/api/auth/guest');
  assert.equal(guestRequest.method, 'POST');
  assert.equal(fixture.app.isGuestUser(), true);
  assert.equal(fixture.app.globalData.accessToken, 'guest-token');

  // 游客点「微信一键登录」：携带游客 token 供服务端迁移数据
  const user = await fixture.app.wxLogin();

  assert.equal(user.id, REAL_USER.id);
  assert.equal(fixture.calls.login, 1);
  assert.equal(loginRequest.data.code, 'wx-one-time-code');
  assert.equal(loginRequest.timeout, 15000);
  assert.equal(loginRequest.header.Authorization, 'Bearer guest-token');
  assert.equal(fixture.app.globalData.accessToken, 'app-token');
  assert.equal(fixture.app.globalData.isNewUser, true);
  assert.equal(fixture.app.isGuestUser(), false);
  assert.equal(fixture.storage.get('accessToken'), 'app-token');
}

async function testDevelopEnvironmentUsesProductionHttps() {
  const fixture = loadApp({
    handleRequest(options) {
      if (options.url.endsWith('/api/auth/guest')) {
        respondGuest(options);
        return;
      }
      options.success({ statusCode: 404, data: {} });
    },
  });

  fixture.app.onLaunch();
  await fixture.app.globalData.sessionRestorePromise;

  assert.equal(fixture.app.globalData.baseUrl, 'https://api.quizapp.chat');
  assert.equal(fixture.calls.requests.length, 1);
  assert.equal(fixture.calls.requests[0].url, 'https://api.quizapp.chat/api/auth/guest');
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
  // 游客创建失败（域名未配置）时静默降级，不报错弹窗
  const restoredUser = await fixture.app.globalData.sessionRestorePromise;
  assert.equal(restoredUser, null);

  await assert.rejects(
    fixture.app.wxLogin(),
    /API 域名未加入微信 request 合法域名/,
  );
  assert.equal(fixture.calls.requests[1].timeout, 15000);
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
      userInfo: { id: 3, nickname: '旧昵称', avatar: '', is_guest: false },
      accessToken: 'cached-token',
    },
    handleRequest(options) {
      options.success({
        statusCode: 200,
        data: { id: 3, nickname: '服务端昵称', avatar: '', is_admin: false, is_guest: false },
      });
    },
  });

  fixture.app.onLaunch();
  const user = await fixture.app.globalData.sessionRestorePromise;

  assert.equal(user.nickname, '服务端昵称');
  assert.equal(fixture.app.isGuestUser(), false);
  assert.equal(fixture.app.globalData.profileRequired, false);
  assert.equal(fixture.calls.login, 0);
  assert.equal(fixture.calls.requests.length, 1);
  assert.equal(fixture.calls.requests[0].header.Authorization, 'Bearer cached-token');
}

async function testExpiredCachedSessionRecoversAsGuest() {
  let guestRequest;
  const fixture = loadApp({
    initialStorage: {
      userInfo: { id: 3, nickname: '旧昵称', avatar: '', is_guest: false },
      accessToken: 'expired-token',
    },
    handleRequest(options) {
      if (options.url.endsWith('/api/auth/me')) {
        options.success({ statusCode: 401, data: { detail: 'expired' } });
        return;
      }
      if (options.url.endsWith('/api/auth/guest')) {
        guestRequest = options;
        respondGuest(options);
        return;
      }
      if (options.url.endsWith('/api/auth/login')) {
        respondRealLogin(options);
        return;
      }
      options.success({ statusCode: 404, data: {} });
    },
  });

  fixture.app.onLaunch();
  const restoredUser = await fixture.app.globalData.sessionRestorePromise;

  // 会话过期：不再停在「未登录」，而是静默重建游客会话
  assert.equal(restoredUser.id, GUEST_USER.id);
  assert.equal(fixture.calls.login, 0);
  assert.equal(fixture.calls.requests.length, 2);
  assert.equal(guestRequest.url, 'https://api.quizapp.chat/api/auth/guest');

  const user = await fixture.app.wxLogin();

  assert.equal(user.nickname, '微信用户');
  assert.equal(fixture.calls.login, 1);
  assert.equal(fixture.calls.requests.length, 3);
  assert.equal(fixture.storage.get('accessToken'), 'app-token');
  assert.equal(fixture.app.isGuestUser(), false);
}

async function testLogoutReturnsToGuestSession() {
  const fixture = loadApp({
    handleRequest(options) {
      if (options.url.endsWith('/api/auth/guest')) {
        respondGuest(options);
        return;
      }
      throw new Error('unexpected request: ' + options.url);
    },
  });
  fixture.app._setSession({ id: 9, nickname: '用户', is_guest: false }, 'token');
  fixture.app.logout();

  // 退出后回到首页，静默转为新的游客会话继续体验
  assert.equal(fixture.calls.relaunches[0], '/pages/index/index');

  fixture.app.onLaunch();
  const user = await fixture.app.globalData.sessionRestorePromise;
  assert.equal(user.id, GUEST_USER.id);
  assert.equal(fixture.app.isGuestUser(), true);
  assert.equal(fixture.calls.login, 0);
  assert.equal(fixture.calls.requests[0].url, 'https://api.quizapp.chat/api/auth/logout');
}

(async () => {
  await testFirstLaunchCreatesSilentGuestSession();
  await testDevelopEnvironmentUsesProductionHttps();
  await testLoginReportsRequestDomainFailure();
  await testLoginReportsAbortedConnection();
  await testCachedSessionIsVerifiedWithoutWxLogin();
  await testExpiredCachedSessionRecoversAsGuest();
  await testLogoutReturnsToGuestSession();
  console.log('miniapp auth tests passed');
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
