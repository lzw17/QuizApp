App({
  globalData: {
    userInfo: null,
    userId: null,
    accessToken: '',
    loginPromise: null,
    sessionRestorePromise: null,
    sessionVersion: 0,
    isNewUser: false,
    baseUrl: 'https://your-server.com', // 生产环境改为实际域名
    devLanUrl: 'http://192.168.71.4:8000', // 局域网真机调试用
  },

  onLaunch() {
    const platform = wx.getSystemInfoSync().platform;
    const accountInfo = wx.getAccountInfoSync ? wx.getAccountInfoSync() : {};
    const envVersion = (accountInfo.miniProgram && accountInfo.miniProgram.envVersion) || 'develop';
    if (envVersion === 'develop') {
      // 开发版使用本地服务；体验版和正式版保留上面的 HTTPS 生产域名。
      this.globalData.baseUrl = platform === 'devtools'
        ? 'http://127.0.0.1:8000'
        : this.globalData.devLanUrl;
    }
    const restorePromise = this._restoreSession();
    this.globalData.sessionRestorePromise = restorePromise;
    restorePromise.finally(() => {
      if (this.globalData.sessionRestorePromise === restorePromise) {
        this.globalData.sessionRestorePromise = null;
      }
    });
  },

  ensureLogin() {
    if (this.globalData.userId && this.globalData.accessToken) {
      return Promise.resolve(this.globalData.userInfo);
    }
    if (this.globalData.sessionRestorePromise) {
      return this.globalData.sessionRestorePromise;
    }
    return Promise.resolve(null);
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
        fail: () => {
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
            resolve(user);
          } else {
            const message = (r.data && r.data.detail) || `登录失败 (${r.statusCode})`;
            reject(new Error(message));
          }
        },
        fail: () => reject(new Error('网络连接失败，请稍后重试')),
      });
    });
  },

  _setSession(user, token) {
    this.globalData.userInfo = user;
    this.globalData.userId = user.id;
    this.globalData.accessToken = token;
    wx.setStorageSync('userInfo', user);
    wx.setStorageSync('accessToken', token);
  },

  clearSession() {
    this.globalData.sessionVersion += 1;
    this.globalData.userInfo = null;
    this.globalData.userId = null;
    this.globalData.accessToken = '';
    this.globalData.isNewUser = false;
    wx.removeStorageSync('userInfo');
    wx.removeStorageSync('accessToken');
  },

  logout() {
    this.clearSession();
    wx.reLaunch({ url: '/pages/login/login' });
  },
});
