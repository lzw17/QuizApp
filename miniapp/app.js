const AUTH_REQUEST_TIMEOUT_MS = 15000;

function describeAuthRequestFailure(error) {
  const errMsg = String((error && error.errMsg) || '').toLowerCase();

  if (errMsg.includes('domain list') || errMsg.includes('url not in domain')) {
    return 'API 域名未加入微信 request 合法域名';
  }
  if (/certificate|err_cert|ssl|tls/.test(errMsg)) {
    return '服务器 HTTPS 证书异常，请联系管理员';
  }
  if (/timeout|timed out/.test(errMsg)) {
    return '登录请求超时，请检查服务器 HTTPS';
  }
  if (/abort|connection reset|connection closed|err_connection/.test(errMsg)) {
    return '服务器连接被中止，请检查 HTTPS/TLS 配置';
  }
  return '网络连接失败，请检查 API 域名与服务器';
}

function logAuthRequestFailure(stage, error) {
  console.error('[auth] request failed', {
    stage,
    errMsg: (error && error.errMsg) || 'unknown',
    errno: error && error.errno,
  });
}

App({
  globalData: {
    userInfo: null,
    userId: null,
    accessToken: '',
    loginPromise: null,
    sessionRestorePromise: null,
    sessionVersion: 0,
    isNewUser: false,
    profileRequired: false,
    baseUrl: 'https://api.quizapp.chat', // 开发者工具、真机、体验版和正式版统一使用生产 HTTPS 域名
    sessionListeners: [],
  },

  onLaunch() {
    if (typeof wx.onNeedPrivacyAuthorization === 'function') {
      wx.onNeedPrivacyAuthorization(resolve => {
        wx.showModal({
          title: '隐私保护提示',
          content: '登录需要使用微信账号标识，用于创建账号并同步你的学习记录。',
          confirmText: '同意并继续',
          cancelText: '暂不登录',
          success: result => resolve({ event: result.confirm ? 'agree' : 'disagree' }),
          fail: () => resolve({ event: 'disagree' }),
        });
      });
    }
    const sessionPromise = this._initializeSession();
    this.globalData.sessionRestorePromise = sessionPromise;
    sessionPromise.finally(() => {
      if (this.globalData.sessionRestorePromise === sessionPromise) {
        this.globalData.sessionRestorePromise = null;
      }
    });
  },

  ensureLogin(options = {}) {
    if (this.globalData.userId && this.globalData.accessToken) {
      return Promise.resolve(this.globalData.userInfo);
    }
    if (this.globalData.sessionRestorePromise) {
      return this.globalData.sessionRestorePromise;
    }
    if (options.autoLogin === false || wx.getStorageSync('manualLoginRequired')) {
      return Promise.resolve(null);
    }
    return this._startWxLogin(false);
  },

  /** 是否已登录（游客态下为 false，页面据此展示登录引导而不是强行跳转） */
  isLoggedIn() {
    return !!(this.globalData.userId && this.globalData.accessToken);
  },

  /**
   * 订阅会话失效事件（401 清会话、主动退出登录等）。
   * 页面据此把自身的 loggedIn 状态同步回游客态，避免 401 后界面仍显示已登录与陈旧数据。
   * 返回取消订阅函数，请在页面 onUnload 中调用。
   */
  onSessionInvalid(listener) {
    if (typeof listener !== 'function') return () => {};
    if (!Array.isArray(this.globalData.sessionListeners)) {
      this.globalData.sessionListeners = [];
    }
    this.globalData.sessionListeners.push(listener);
    return () => {
      const listeners = this.globalData.sessionListeners || [];
      const index = listeners.indexOf(listener);
      if (index >= 0) listeners.splice(index, 1);
    };
  },

  _notifySessionInvalid() {
    const listeners = (this.globalData.sessionListeners || []).slice();
    listeners.forEach(listener => {
      try {
        listener();
      } catch (error) {
        console.error('[session] listener failed', error);
      }
    });
  },

  /**
   * 用户主动触发的登录引导。
   * 只在用户点击了需要登录的功能时调用，由用户确认后再进入登录页，
   * 满足「先浏览体验，再自行选择授权登录」的审核要求。
   */
  promptLogin(options = {}) {
    return new Promise(resolve => {
      wx.showModal({
        title: options.title || '需要登录',
        content: options.content || '登录后即可上传资料、生成专属题库，并同步你的练习与错题记录。',
        confirmText: options.confirmText || '微信登录',
        cancelText: options.cancelText || '先看看',
        success: res => {
          if (!res.confirm) {
            resolve(false);
            return;
          }
          wx.navigateTo({ url: '/pages/login/login' });
          resolve(true);
        },
        fail: () => resolve(false),
      });
    });
  },

  async _initializeSession() {
    return this._restoreSession();
  },

  _restoreSession() {
    const sessionVersion = this.globalData.sessionVersion;
    const cached = wx.getStorageSync('userInfo');
    const token = wx.getStorageSync('accessToken');
    if (!cached || !cached.id || !token) {
      this.clearSession();
      return Promise.resolve(null);
    }

    return new Promise((resolve) => {
      wx.request({
        url: `${this.globalData.baseUrl}/api/auth/me`,
        header: { Authorization: `Bearer ${token}` },
        timeout: AUTH_REQUEST_TIMEOUT_MS,
        success: (res) => {
          if (sessionVersion !== this.globalData.sessionVersion) {
            resolve(null);
            return;
          }
          if (res.statusCode === 200 && res.data && res.data.id) {
            this._setSession(res.data, token);
            resolve(res.data);
          } else if (res.statusCode === 401) {
            this.clearSession();
            resolve(null);
          } else {
            // 非鉴权错误时保留缓存，具体请求仍由服务端校验 token。
            this._setSession(cached, token);
            resolve(cached);
          }
        },
        fail: error => {
          logAuthRequestFailure('restore-session', error);
          if (sessionVersion !== this.globalData.sessionVersion) {
            resolve(null);
            return;
          }
          this._setSession(cached, token);
          resolve(cached);
        },
      });
    });
  },

  wxLogin(options = {}) {
    const force = options.force === true;
    wx.removeStorageSync('manualLoginRequired');
    if (this.globalData.sessionRestorePromise) {
      return this.globalData.sessionRestorePromise.then(user => {
        if (user && !force) return user;
        return this._startWxLogin(force);
      });
    }
    return this._startWxLogin(force);
  },

  _startWxLogin(force) {
    if (!force && this.globalData.userId && this.globalData.accessToken) {
      return Promise.resolve(this.globalData.userInfo);
    }
    if (this.globalData.loginPromise) return this.globalData.loginPromise;

    const startLogin = () => new Promise((resolve, reject) => {
      wx.login({
        success: res => res.code ? resolve(res.code) : reject(new Error('获取微信登录凭证失败')),
        fail: () => reject(new Error('无法连接微信登录服务')),
      });
    });
    this.globalData.loginPromise = startLogin()
      .then(code => this._doLogin(code))
      .finally(() => { this.globalData.loginPromise = null; });
    return this.globalData.loginPromise;
  },

  _doLogin(code) {
    const self = this;
    return new Promise((resolve, reject) => {
      wx.request({
        url: `${self.globalData.baseUrl}/api/auth/login`,
        method: 'POST',
        data: { code },
        timeout: AUTH_REQUEST_TIMEOUT_MS,
        success(r) {
          if (r.statusCode === 200) {
            const user = r.data && r.data.user;
            const token = r.data && r.data.access_token;
            if (!user || !user.id || !token) {
              reject(new Error('登录响应格式错误'));
              return;
            }
            const isNew = r.data.is_new;
            self.globalData.isNewUser = isNew;
            self._setSession(user, token);
            wx.removeStorageSync('manualLoginRequired');
            resolve(user);
          } else {
            const message = (r.data && r.data.detail) || `登录失败 (${r.statusCode})`;
            reject(new Error(message));
          }
        },
        fail(error) {
          logAuthRequestFailure('login', error);
          reject(new Error(describeAuthRequestFailure(error)));
        },
      });
    });
  },

  _setSession(user, token) {
    this.globalData.userInfo = user;
    this.globalData.userId = user.id;
    this.globalData.accessToken = token;
    this.globalData.profileRequired = false;
    wx.setStorageSync('userInfo', user);
    wx.setStorageSync('accessToken', token);
  },

  clearSession() {
    this.globalData.sessionVersion += 1;
    this.globalData.userInfo = null;
    this.globalData.userId = null;
    this.globalData.accessToken = '';
    this.globalData.isNewUser = false;
    this.globalData.profileRequired = false;
    wx.removeStorageSync('userInfo');
    wx.removeStorageSync('accessToken');
    if (typeof wx.getStorageInfoSync === 'function') {
      const storageInfo = wx.getStorageInfoSync();
      (storageInfo.keys || []).filter(key => key.indexOf('exam-result-') === 0)
        .forEach(key => wx.removeStorageSync(key));
    }
    // 广播给各页面：把自身 UI 同步回游客态（401 与主动退出都会走到这里）
    this._notifySessionInvalid();
  },

  logout() {
    const token = this.globalData.accessToken;
    if (token) {
      wx.request({
        url: `${this.globalData.baseUrl}/api/auth/logout`,
        method: 'POST',
        header: { Authorization: `Bearer ${token}` },
        complete: () => {},
      });
    }
    this.clearSession();
    wx.setStorageSync('manualLoginRequired', true);
    // 退出后回到首页以游客身份浏览，不强制跳登录页
    wx.reLaunch({ url: '/pages/index/index' });
  },
});
