const app = getApp();

Page({
  data: {
    stage: 'login',   // 'login' | 'setup'
    avatarUrl: '',
    nickname: '',
    submitting: false,
    logging: false,
    userId: null,
    isEdit: false,
  },

  onLoad(options) {
    const isEdit = options.edit === '1';
    this.setData({ isEdit });

    if (isEdit) {
      const user = app.globalData.userInfo || wx.getStorageSync('userInfo') || {};
      this.setData({
        stage: 'setup',
        userId: user.id,
        avatarUrl: user.avatar || '',
        nickname: user.nickname || '',
      });
      return;
    }

    const cached = wx.getStorageSync('userInfo');
    if (cached && cached.id) {
      // 有缓存直接进首页
      wx.reLaunch({ url: '/pages/index/index' });
      return;
    }
    // 无缓存时 stage 保持 'login'，显示登录按钮
  },

  async onWxLogin() {
    if (this.data.logging) return;
    this.setData({ logging: true });
    try {
      const user = await app.wxLogin();
      if (!user) throw new Error('登录失败');
      wx.reLaunch({ url: '/pages/index/index' });
    } catch {
      this.setData({ logging: false });
      wx.showToast({ title: '登录失败，请重试', icon: 'none' });
    }
  },

  onChooseAvatar(e) {
    this.setData({ avatarUrl: e.detail.avatarUrl });
  },

  onNicknameInput(e) {
    this.setData({ nickname: e.detail.value });
  },

  async onSubmit() {
    const { avatarUrl, nickname, userId, isEdit } = this.data;
    if (!nickname.trim()) {
      wx.showToast({ title: '请输入昵称', icon: 'none' }); return;
    }
    if (!userId) {
      wx.showToast({ title: '请先登录', icon: 'none' }); return;
    }
    this.setData({ submitting: true });
    try {
      let finalAvatar = avatarUrl;
      if (avatarUrl && (avatarUrl.startsWith('wxfile://') || avatarUrl.includes('/tmp/'))) {
        finalAvatar = await this._uploadAvatar(avatarUrl, userId);
      }
      await this._updateProfile(userId, nickname.trim(), finalAvatar);
      wx.showToast({ title: isEdit ? '修改成功' : '设置成功', icon: 'success' });
      setTimeout(() => {
        isEdit ? wx.navigateBack() : wx.reLaunch({ url: '/pages/index/index' });
      }, 1200);
    } catch {
      this.setData({ submitting: false });
    }
  },

  onSkip() {
    wx.reLaunch({ url: '/pages/index/index' });
  },

  _uploadAvatar(filePath, userId) {
    return new Promise((resolve) => {
      wx.uploadFile({
        url: `${app.globalData.baseUrl}/api/auth/avatar`,
        filePath,
        name: 'file',
        formData: { user_id: String(userId) },
        success(res) {
          try {
            const data = typeof res.data === 'string' ? JSON.parse(res.data) : res.data;
            resolve(res.statusCode === 200 && data.avatar_url ? data.avatar_url : filePath);
          } catch { resolve(filePath); }
        },
        fail: () => resolve(filePath),
      });
    });
  },

  _updateProfile(userId, nickname, avatar) {
    return new Promise((resolve, reject) => {
      wx.request({
        url: `${app.globalData.baseUrl}/api/auth/profile`,
        method: 'PUT',
        data: { user_id: userId, nickname, avatar },
        header: { 'Content-Type': 'application/json' },
        success(res) {
          if (res.statusCode === 200) {
            app.globalData.userInfo = res.data;
            wx.setStorageSync('userInfo', res.data);
            resolve(res.data);
          } else {
            wx.showToast({ title: '更新失败，请重试', icon: 'none' });
            reject(new Error('更新失败'));
          }
        },
        fail(err) {
          wx.showToast({ title: '网络错误', icon: 'none' });
          reject(err);
        },
      });
    });
  },
});
