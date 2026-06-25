App({
  globalData: {
    userInfo: null,
    userId: null,
    baseUrl: 'https://your-server.com', // 生产环境改为实际域名
  },

  onLaunch() {
    // 开发环境使用本机 IP
    if (wx.getSystemInfoSync().platform === 'devtools') {
      this.globalData.baseUrl = 'http://127.0.0.1:8000';
    }
    this._autoLogin();
  },

  _autoLogin() {
    const cached = wx.getStorageSync('userInfo');
    if (cached) {
      this.globalData.userInfo = cached;
      this.globalData.userId = cached.id;
      return;
    }
    wx.login({
      success: (res) => {
        if (res.code) {
          this._doLogin(res.code);
        }
      },
    });
  },

  _doLogin(code) {
    const self = this;
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
        }
      },
    });
  },
});
