const { request, getUserId } = require('../../utils/request');
const app = getApp();

Page({
  data: {
    activeTab: 'wrong',
    wrongList: [],
    starList: [],
    banks: [],
    filterBankId: '',
    loading: false,
    typeLabel: { single: '单选', multi: '多选', judge: '判断' },
  },

  onLoad(options) {
    if (options.bank_id) this.setData({ filterBankId: parseInt(options.bank_id) });
  },

  onShow() {
    const pendingBankId = wx.getStorageSync('wrongBookFilterBankId');
    if (pendingBankId) {
      wx.removeStorageSync('wrongBookFilterBankId');
      this.setData({ filterBankId: parseInt(pendingBankId) || '' });
    }
    // 更新自定义 tabBar 选中状态
    if (typeof this.getTabBar === 'function' && this.getTabBar()) {
      this.getTabBar().setData({ selected: 1 });
    }
    this._loadAll(pendingBankId ? (parseInt(pendingBankId) || '') : undefined);
  },
  onPullDownRefresh() { this._loadAll(); wx.stopPullDownRefresh(); },

  switchTab(e) {
    this.setData({ activeTab: e.currentTarget.dataset.tab });
    if (e.currentTarget.dataset.tab === 'star') this._loadStars();
  },

  setFilter(e) {
    const id = e.currentTarget.dataset.id;
    this.setData({ filterBankId: id ? parseInt(id) : '' });
    this._loadWrong();
  },

  async _loadAll(filterBankId) {
    await this._loadBanks();
    await this._loadWrong(filterBankId);
    if (this.data.activeTab === 'star') {
      await this._loadStars(filterBankId);
    }
  },

  async _loadWrong(filterBankId = this.data.filterBankId) {
    const uid = await getUserId();
    if (!uid) return;
    try {
      let url = '/api/wrong-questions';
      if (filterBankId) url += `?bank_id=${filterBankId}`;
      const list = await request({ url });
      this.setData({ wrongList: list.map(item => ({
        ...item,
        answered_at: item.answered_at ? item.answered_at.slice(0, 10) : '',
      })) });
    } catch {}
  },

  async _loadStars(filterBankId = this.data.filterBankId) {
    const uid = await getUserId();
    if (!uid) return;
    try {
      const bankQuery = filterBankId ? `?bank_id=${filterBankId}` : '';
      const starList = await request({ url: `/api/starred-questions${bankQuery}` });
      this.setData({ starList });
    } catch {}
  },

  async _loadBanks() {
    try {
      const list = await request({ url: '/api/banks?limit=50' });
      this.setData({ banks: list });
    } catch {}
  },

  async removeStar(e) {
    const uid = await getUserId();
    if (!uid) return;
    const { id, bank } = e.currentTarget.dataset;
    try {
      await request({ url: '/api/star', method: 'POST', data: { bank_id: bank, question_id: id } });
      this._loadStars();
    } catch {}
  },

  practiceWrong() {
    const { filterBankId, wrongList } = this.data;
    if (!wrongList.length) return;
    if (!filterBankId && new Set(wrongList.map(item => item.bank_id)).size > 1) {
      wx.showToast({ title: '请先选择题库', icon: 'none' });
      return;
    }
    const bankId = filterBankId || wrongList[0].bank_id;
    wx.navigateTo({ url: `/pages/practice/practice?bank_id=${bankId}&mode=wrong` });
  },

  memorizeWrong() {
    const { filterBankId, wrongList } = this.data;
    if (!wrongList.length) return;
    if (!filterBankId && new Set(wrongList.map(item => item.bank_id)).size > 1) {
      wx.showToast({ title: '请先选择题库', icon: 'none' });
      return;
    }
    const bankId = filterBankId || wrongList[0].bank_id;
    wx.navigateTo({ url: `/pages/practice/practice?bank_id=${bankId}&mode=memorize&source=wrong` });
  },

  practiceStar() {
    const { starList } = this.data;
    if (!starList.length) return;
    if (new Set(starList.map(item => item.bank_id)).size > 1) {
      wx.showToast({ title: '请先选择题库', icon: 'none' });
      return;
    }
    wx.navigateTo({ url: `/pages/practice/practice?bank_id=${starList[0].bank_id}&mode=starred` });
  },

  memorizeStar() {
    const { starList } = this.data;
    if (!starList.length) return;
    if (new Set(starList.map(item => item.bank_id)).size > 1) {
      wx.showToast({ title: '请先选择题库', icon: 'none' });
      return;
    }
    wx.navigateTo({ url: `/pages/practice/practice?bank_id=${starList[0].bank_id}&mode=memorize&source=starred` });
  },
});
