const { request, getUserId } = require('../../utils/request');
const app = getApp();

Page({
  data: {
    userInfo: {},
    stats: {},
    levelLabel: '初学者',
  },

  onLoad()  { this._loadData(); },
  onShow()  { this._loadData(); },
  onPullDownRefresh() { this._loadData(); wx.stopPullDownRefresh(); },

  async _loadData() {
    const userInfo = app.globalData.userInfo || wx.getStorageSync('userInfo') || {};
    this.setData({ userInfo });

    const uid = await getUserId();
    if (!uid) return;
    try {
      const stats = await request({ url: `/api/stats?user_id=${uid}` });
      this.setData({ stats, levelLabel: this._getLevel(stats.total_answered) });
    } catch {}
  },

  async changeAvatar() {
    const uid = await getUserId();
    if (!uid) {
      wx.showToast({ title: '请先登录', icon: 'none' });
      return;
    }
    wx.chooseMedia({
      count: 1,
      mediaType: ['image'],
      sizeType: ['compressed'],
      success: (res) => {
        const tempPath = res.tempFiles[0].tempFilePath;
        wx.uploadFile({
          url: `${app.globalData.baseUrl}/api/auth/avatar`,
          filePath: tempPath,
          name: 'file',
          formData: { user_id: String(uid) },
          success: (r) => {
            const data = typeof r.data === 'string' ? JSON.parse(r.data) : r.data;
            if (r.statusCode === 200 && data.avatar_url) {
              const userInfo = Object.assign({}, this.data.userInfo, { avatar: data.avatar_url });
              this.setData({ userInfo });
              app.globalData.userInfo = userInfo;
              wx.setStorageSync('userInfo', userInfo);
              wx.showToast({ title: '头像已更新', icon: 'success' });
            } else {
              wx.showToast({ title: '上传失败', icon: 'none' });
            }
          },
          fail: () => wx.showToast({ title: '网络错误', icon: 'none' }),
        });
      },
    });
  },

  goSettings() { wx.navigateTo({ url: '/pages/settings/settings' }); },

  _getLevel(total) {
    if (total >= 1000) return '学霸';
    if (total >= 500)  return '进阶者';
    if (total >= 100)  return '学习中';
    return '初学者';
  },

  goWrongBook() { wx.switchTab({ url: '/pages/wrong-book/wrong-book' }); },
  goUpload()    { wx.navigateTo({ url: '/pages/upload/upload' }); },
  goManage()    { wx.navigateTo({ url: '/pages/manage/manage' }); },
});
