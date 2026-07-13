const app = getApp();
const { request, uploadFile } = require('../../utils/request');

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

  async onLoad(options) {
    const isEdit = options.edit === '1';
    this.setData({ isEdit });
    const user = await app.ensureLogin();

    if (isEdit) {
      if (!user) {
        wx.reLaunch({ url: '/pages/login/login' });
        return;
      }
      this.setData({
        stage: 'setup',
        userId: user.id,
        avatarUrl: user.avatar || '',
        nickname: user.nickname || '',
      });
      return;
    }

    if (user) {
      wx.reLaunch({ url: '/pages/index/index' });
    }
  },

  async onWxLogin() {
    if (this.data.logging) return;
    this.setData({ logging: true });
    try {
      const user = await app.wxLogin();
      if (!user) throw new Error('登录失败');
      if (app.globalData.isNewUser) {
        this.setData({
          stage: 'setup',
          logging: false,
          userId: user.id,
          avatarUrl: user.avatar || '',
          nickname: '',
        });
      } else {
        wx.reLaunch({ url: '/pages/index/index' });
      }
    } catch (error) {
      this.setData({ logging: false });
      wx.showToast({ title: error.message || '登录失败，请重试', icon: 'none' });
    }
  },

  onChooseAvatar(e) {
    this.setData({ avatarUrl: e.detail.avatarUrl });
  },

  onNicknameInput(e) {
    this.setData({ nickname: e.detail.value });
  },

  async onSubmit() {
    const { avatarUrl, nickname, isEdit } = this.data;
    if (!nickname.trim()) {
      wx.showToast({ title: '请输入昵称', icon: 'none' }); return;
    }
    if (!app.globalData.accessToken) {
      wx.showToast({ title: '请先登录', icon: 'none' }); return;
    }
    this.setData({ submitting: true });
    try {
      let finalAvatar = avatarUrl;
      if (avatarUrl && (avatarUrl.startsWith('wxfile://') || avatarUrl.includes('/tmp/'))) {
        finalAvatar = await this._uploadAvatar(avatarUrl);
      }
      await this._updateProfile(nickname.trim(), finalAvatar);
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

  async _uploadAvatar(filePath) {
    const data = await uploadFile(filePath, {}, { url: '/api/auth/avatar' });
    return data.avatar_url || '';
  },

  async _updateProfile(nickname, avatar) {
    const user = await request({
      url: '/api/auth/profile',
      method: 'PUT',
      data: { nickname, avatar },
    });
    app._setSession(user, app.globalData.accessToken);
    return user;
  },
});
