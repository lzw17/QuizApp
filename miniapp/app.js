App({
  globalData: {
    userInfo: null,
    userId: null,
    loginPromise: null,
    baseUrl: 'https://your-server.com', // 生产环境改为实际域名
  },

  onLaunch() {
    // 开发环境使用本机 IP
    if (wx.getSystemInfoSync().platform === 'devtools') {
      this.globalData.baseUrl = 'http://127.0.0.1:8000';
    }
    this.globalData.loginPromise = this._autoLogin();
  },

  ensureLogin() {
    if (this.globalData.userId) {
      return Promise.resolve(this.globalData.userInfo);
    }
    if (!this.globalData.loginPromise) {
      this.globalData.loginPromise = this._autoLogin();
    }
    return this.globalData.loginPromise;
  },

  _autoLogin() {
    const cached = wx.getStorageSync('userInfo');
    if (cached && cached.id) {
      this.globalData.userInfo = cached;
      this.globalData.userId = cached.id;
      return Promise.resolve(cached);
    }

    return new Promise((resolve, reject) => {
      wx.login({
        success: (res) => {
          if (!res.code) {
            reject(new Error('微信登录未返回 code'));
            return;
          }
          this._doLogin(res.code).then(resolve).catch(reject);
        },
        fail: reject,
      });
    });
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
            const user = r.data.user;
            self.globalData.userInfo = user;
            self.globalData.userId = user.id;
            wx.setStorageSync('userInfo', user);
            resolve(user);
          } else {
            reject(new Error('登录失败'));
          }
        },
        fail: reject,
      });
    });
  },
});
