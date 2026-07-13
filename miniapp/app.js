App({
  globalData: {
    userInfo: null,
    userId: null,
    loginPromise: null,
    isNewUser: false,
    baseUrl: 'https://your-server.com', // 生产环境改为实际域名
    devLanUrl: 'http://192.168.71.4:8000', // 局域网真机调试用
  },

  onLaunch() {
    const platform = wx.getSystemInfoSync().platform;
    if (platform === 'devtools') {
      this.globalData.baseUrl = 'http://127.0.0.1:8000';
    } else {
      // 真机调试时使用局域网 IP（手机与电脑需在同一 WiFi）
      this.globalData.baseUrl = this.globalData.devLanUrl;
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
    // 无缓存时不自动登录，由登录页按钮触发
    return Promise.resolve(null);
  },

  wxLogin() {
    if (this.globalData.userId) {
      return Promise.resolve(this.globalData.userInfo);
    }
    return new Promise((resolve, reject) => {
      wx.login({
        success: (res) => {
          if (!res.code) { reject(new Error('获取 code 失败')); return; }
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
          console.log('[_doLogin] status:', r.statusCode, 'data:', JSON.stringify(r.data));
          if (r.statusCode === 200) {
            const user = r.data && r.data.user;
            if (!user || !user.id) {
              console.error('[_doLogin] 响应格式异常:', JSON.stringify(r.data));
              reject(new Error('登录响应格式错误'));
              return;
            }
            const isNew = r.data.is_new;
            self.globalData.userInfo = user;
            self.globalData.userId = user.id;
            self.globalData.isNewUser = isNew;
            wx.setStorageSync('userInfo', user);
            resolve(user);
          } else {
            console.error('[_doLogin] HTTP错误:', r.statusCode, JSON.stringify(r.data));
            reject(new Error(`登录失败(${r.statusCode})`));
          }
        },
        fail: reject,
      });
    });
  },
});
