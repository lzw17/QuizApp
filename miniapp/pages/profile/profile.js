const { request, getUserId } = require('../../utils/request');
const app = getApp();

Page({
  data: {
    userInfo: {},
    stats: {},
    levelLabel: '初学者',
    statusBarHeight: 0,
  },

  onLoad() {
    const { statusBarHeight } = wx.getWindowInfo();
    this.setData({ statusBarHeight });
    this._loadData();
  },
  onShow() {
    // 更新自定义 tabBar 选中状态
    if (typeof this.getTabBar === 'function' && this.getTabBar()) {
      this.getTabBar().setData({ selected: 2 });
    }
    this._loadData();
  },
  onPullDownRefresh() { this._loadData(); wx.stopPullDownRefresh(); },

  async _loadData() {
    const userInfo = app.globalData.userInfo || wx.getStorageSync('userInfo') || {};
    this.setData({ userInfo });

    const uid = await getUserId();
    if (!uid) return;
    try {
      const stats = await request({ url: '/api/stats' });
      this.setData({ stats, levelLabel: this._getLevel(stats.total_answered) });
    } catch {}
  },

  _getLevel(total) {
    if (total >= 1000) return '学霸';
    if (total >= 500)  return '进阶者';
    if (total >= 100)  return '学习中';
    return '初学者';
  },

  goEditProfile() { wx.navigateTo({ url: '/pages/login/login?edit=1' }); },
  goWrongBook() { wx.switchTab({ url: '/pages/wrong-book/wrong-book' }); },
  goReport() { wx.navigateTo({ url: '/pages/report/report' }); },
  goPrivacy() { wx.navigateTo({ url: '/pages/privacy/privacy' }); },
  goUpload()    { wx.navigateTo({ url: '/pages/upload/upload' }); },
  goManage()    { wx.navigateTo({ url: '/pages/manage/manage' }); },
  logout() {
    wx.showModal({
      title: '退出登录',
      content: '退出后，本机将清除登录状态，学习记录仍保留在账号中。',
      confirmText: '退出',
      success: res => { if (res.confirm) app.logout(); },
    });
  },
  deleteAccount() {
    wx.showModal({
      title: '注销账号',
      content: '注销后会清理作答记录、收藏和学习进度，且无法恢复。确定继续吗？',
      confirmText: '确认注销',
      confirmColor: '#FF4D4F',
      success: async res => {
        if (!res.confirm) return;
        try {
          await request({ url: '/api/auth/account', method: 'DELETE' });
          app.clearSession();
          wx.setStorageSync('manualLoginRequired', true);
          wx.reLaunch({ url: '/pages/login/login' });
        } catch {}
      },
    });
  },
});
