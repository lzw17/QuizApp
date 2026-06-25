const { request } = require('../../utils/request');
const app = getApp();

Page({
  data: {
    banks: [],
    categories: [],
    activeCategory: '',
    stats: {},
    loading: false,
    userId: null,
    page: 0,
    hasMore: true,
  },

  onLoad() {
    this.setData({ userId: app.globalData.userId });
    this._loadBanks(true);
    this._loadStats();
  },

  onShow() {
    // 每次显示刷新（上传完成后返回）
    this._loadBanks(true);
    this._loadStats();
  },

  onPullDownRefresh() {
    this._loadBanks(true);
    wx.stopPullDownRefresh();
  },

  onReachBottom() {
    if (this.data.hasMore && !this.data.loading) {
      this._loadBanks(false);
    }
  },

  async _loadBanks(reset) {
    if (this.data.loading) return;
    const skip = reset ? 0 : this.data.page * 20;
    this.setData({ loading: true });
    try {
      const params = new URLSearchParams({ skip, limit: 20 });
      if (this.data.activeCategory) params.append('category', this.data.activeCategory);
      const banks = await request({ url: `/api/banks?${params}` });
      const merged = reset ? banks : [...this.data.banks, ...banks];
      // 收集分类
      const catSet = new Set(merged.map(b => b.category).filter(Boolean));
      this.setData({
        banks: merged,
        categories: [...catSet],
        page: reset ? 1 : this.data.page + 1,
        hasMore: banks.length === 20,
        loading: false,
      });
    } catch {
      this.setData({ loading: false });
    }
  },

  async _loadStats() {
    const uid = app.globalData.userId;
    if (!uid) return;
    try {
      const stats = await request({ url: `/api/stats?user_id=${uid}` });
      this.setData({ stats });
    } catch {}
  },

  filterCategory(e) {
    const category = e.currentTarget.dataset.category;
    this.setData({ activeCategory: category });
    this._loadBanks(true);
  },

  goUpload() {
    wx.navigateTo({ url: '/pages/upload/upload' });
  },

  goDetail(e) {
    const id = e.currentTarget.dataset.id;
    wx.navigateTo({ url: `/pages/bank-detail/bank-detail?id=${id}` });
  },
});
