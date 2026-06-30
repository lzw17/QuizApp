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
