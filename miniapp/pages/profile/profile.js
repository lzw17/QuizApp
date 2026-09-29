const { request, getUserId } = require('../../utils/request');
const app = getApp();

const share = require('../../utils/share');

Page({
  onShareAppMessage() { return share.shareApp(this); },
  onShareTimeline() { return share.shareTimeline(this); },
  data: {
    userInfo: {},
    stats: {},
    levelLabel: '初学者',
    loggedIn: false,
    isGuest: false,
    statusBarHeight: 0,
  },

  onLoad() {
    const { statusBarHeight } = wx.getWindowInfo();
    this.setData({ statusBarHeight });
    // 会话失效时同步回游客态，避免继续展示已登录界面与陈旧统计
    this._unsubscribeSession = typeof app.onSessionInvalid === 'function'
      ? app.onSessionInvalid(() => this._resetToGuest())
      : null;
  },

  onUnload() {
    if (this._unsubscribeSession) this._unsubscribeSession();
  },

  _resetToGuest() {
    this.setData({ loggedIn: false, userInfo: {}, stats: {}, levelLabel: '初学者' });
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
    const isGuest = app.isGuestUser();
    const userInfo = app.globalData.userInfo || wx.getStorageSync('userInfo') || {};
    this.setData({ userInfo });

    const uid = await getUserId();
    // 游客会话不算「已登录」：不显示昵称/退出/注销，但统计照常展示
    this.setData({ loggedIn: !!uid && !isGuest, isGuest });
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

  // 游客或未登录时点击头像卡片进入登录页（用户主动触发），正式账号则进入资料编辑
  goEditProfile() {
    if (app.isGuestUser() || !app.isLoggedIn()) {
      wx.navigateTo({ url: '/pages/login/login' });
      return;
    }
    wx.navigateTo({ url: '/pages/login/login?edit=1' });
  },
  goBanks() { wx.switchTab({ url: '/pages/index/index' }); },
  _goReviewTab(tab) {
    wx.setStorageSync('wrongBookActiveTab', tab);
    wx.switchTab({ url: '/pages/wrong-book/wrong-book' });
  },
  goWrongBook() { this._goReviewTab('wrong'); },
  goStarred() { this._goReviewTab('star'); },
  goReport() {
    if (!app.isLoggedIn()) { app.promptLogin({ content: '查看学习报告需要登录，是否立即微信登录？' }); return; }
    wx.navigateTo({ url: '/pages/report/report' });
  },
  goPrivacy() { wx.navigateTo({ url: '/pages/privacy/privacy' }); },
  goUpload() {
    if (app.isGuestUser() || !app.isLoggedIn()) { app.promptLogin({ content: '上传资料并生成题库需要登录，是否立即微信登录？' }); return; }
    wx.navigateTo({ url: '/pages/upload/upload' });
  },
  goManage() {
    if (app.isGuestUser() || !app.isLoggedIn()) { app.promptLogin({ content: '题库管理需要登录，是否立即微信登录？' }); return; }
    wx.navigateTo({ url: '/pages/manage/manage' });
  },
  clearCache() {
    wx.showModal({
      title: '清理缓存',
      content: '仅清理本地题目和考试缓存，保留当前登录状态。',
      confirmText: '清理',
      success: res => {
        if (!res.confirm) return;
        const token = wx.getStorageSync('accessToken');
        const userInfo = wx.getStorageSync('userInfo');
        const manualLoginRequired = wx.getStorageSync('manualLoginRequired');
        wx.clearStorageSync();
        if (token) wx.setStorageSync('accessToken', token);
        if (userInfo) wx.setStorageSync('userInfo', userInfo);
        if (manualLoginRequired) wx.setStorageSync('manualLoginRequired', true);
        wx.showToast({ title: '缓存已清理', icon: 'success' });
      },
    });
  },
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
      content: '注销后会删除你创建的题库，并清理作答记录、收藏和学习进度，且无法恢复。确定继续吗？',
      confirmText: '确认注销',
      confirmColor: '#FF4D4F',
      success: async res => {
        if (!res.confirm) return;
        try {
          await request({ url: '/api/auth/account', method: 'DELETE' });
          app.clearSession();
          wx.setStorageSync('manualLoginRequired', true);
          // 注销后回到首页以游客身份浏览，不强制进入登录页
          wx.reLaunch({ url: '/pages/index/index' });
        } catch {}
      },
    });
  },
});
