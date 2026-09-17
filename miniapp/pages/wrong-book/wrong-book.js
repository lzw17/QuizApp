const { request, getUserId } = require('../../utils/request');
const app = getApp();

Page({
  data: {
    activeTab: 'wrong',
    wrongList: [],
    starList: [],
    wrongTotal: 0,
    starTotal: 0,
    wrongHasMore: false,
    starHasMore: false,
    wrongLoadingMore: false,
    starLoadingMore: false,
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
  onPullDownRefresh() {
    this._loadAll().finally(() => wx.stopPullDownRefresh());
  },

  onReachBottom() {
    if (this.data.activeTab === 'star' && this.data.starHasMore) {
      this._loadStars(undefined, true);
    } else if (this.data.activeTab === 'wrong' && this.data.wrongHasMore) {
      this._loadWrong(undefined, true);
    }
  },

  switchTab(e) {
    this.setData({ activeTab: e.currentTarget.dataset.tab });
    if (e.currentTarget.dataset.tab === 'star') this._loadStars(undefined, false);
  },

  setFilter(e) {
    const id = e.currentTarget.dataset.id;
    this.setData({ filterBankId: id ? parseInt(id) : '' });
    if (this.data.activeTab === 'star') this._loadStars(undefined, false);
    else this._loadWrong(undefined, false);
  },

  async _loadAll(filterBankId) {
    await this._loadBanks();
    await this._loadWrong(filterBankId);
    if (this.data.activeTab === 'star') {
      await this._loadStars(filterBankId);
    }
  },

  async _loadWrong(filterBankId = this.data.filterBankId, append = false) {
    if (append && this._wrongLoading) return;
    const uid = await getUserId();
    if (!uid) return;
    const requestId = (this._wrongRequestId || 0) + 1;
    this._wrongRequestId = requestId;
    this._wrongLoading = true;
    this.setData({ wrongLoadingMore: append });
    try {
      const skip = append ? this.data.wrongList.length : 0;
      const bankQuery = filterBankId ? `&bank_id=${filterBankId}` : '';
      const [list, countInfo] = await Promise.all([
        request({ url: `/api/wrong-questions?skip=${skip}&limit=50${bankQuery}` }),
        append
          ? Promise.resolve({ total: this.data.wrongTotal })
          : request({ url: `/api/questions/count?mode=wrong${bankQuery}` }),
      ]);
      const page = list.map(item => ({
        ...item,
        answered_at: item.answered_at ? item.answered_at.slice(0, 10) : '',
      }));
      if (requestId !== this._wrongRequestId) return;
      const wrongList = append ? this.data.wrongList.concat(page) : page;
      const wrongTotal = Number(countInfo.total || wrongList.length);
      this.setData({
        wrongList,
        wrongTotal,
        wrongHasMore: wrongList.length < wrongTotal && page.length > 0,
      });
    } catch {} finally {
      if (requestId === this._wrongRequestId) {
        this._wrongLoading = false;
        this.setData({ wrongLoadingMore: false });
      }
    }
  },

  async _loadStars(filterBankId = this.data.filterBankId, append = false) {
    if (append && this._starLoading) return;
    const uid = await getUserId();
    if (!uid) return;
    const requestId = (this._starRequestId || 0) + 1;
    this._starRequestId = requestId;
    this._starLoading = true;
    this.setData({ starLoadingMore: append });
    try {
      const skip = append ? this.data.starList.length : 0;
      const bankQuery = filterBankId ? `&bank_id=${filterBankId}` : '';
      const [page, countInfo] = await Promise.all([
        request({ url: `/api/starred-questions?skip=${skip}&limit=50${bankQuery}` }),
        append
          ? Promise.resolve({ total: this.data.starTotal })
          : request({ url: `/api/questions/count?mode=starred${bankQuery}` }),
      ]);
      if (requestId !== this._starRequestId) return;
      const starList = append ? this.data.starList.concat(page) : page;
      const starTotal = Number(countInfo.total || starList.length);
      this.setData({
        starList,
        starTotal,
        starHasMore: starList.length < starTotal && page.length > 0,
      });
    } catch {} finally {
      if (requestId === this._starRequestId) {
        this._starLoading = false;
        this.setData({ starLoadingMore: false });
      }
    }
  },

  async _loadBanks() {
    try {
      const list = [];
      const pageSize = 100;
      for (let skip = 0; skip < 10000; skip += pageSize) {
        const page = await request({ url: `/api/banks?skip=${skip}&limit=${pageSize}` });
        list.push(...page);
        if (page.length < pageSize) break;
      }
      this.setData({ banks: list });
    } catch {}
  },

  async removeStar(e) {
    const uid = await getUserId();
    if (!uid) return;
    const { id, bank } = e.currentTarget.dataset;
    try {
      await request({ url: '/api/star', method: 'POST', data: { bank_id: bank, question_id: id } });
      this._loadStars(undefined, false);
    } catch {}
  },

  practiceWrong() {
    const { filterBankId, wrongList } = this.data;
    if (!wrongList.length) return;
    const bankQuery = filterBankId ? `&bank_id=${filterBankId}` : '';
    wx.navigateTo({ url: `/pages/practice/practice?mode=wrong${bankQuery}` });
  },

  memorizeWrong() {
    const { filterBankId, wrongList } = this.data;
    if (!wrongList.length) return;
    const bankQuery = filterBankId ? `&bank_id=${filterBankId}` : '';
    wx.navigateTo({ url: `/pages/practice/practice?mode=memorize&source=wrong${bankQuery}` });
  },

  practiceStar() {
    const { filterBankId, starList } = this.data;
    if (!starList.length) return;
    const bankQuery = filterBankId ? `&bank_id=${filterBankId}` : '';
    wx.navigateTo({ url: `/pages/practice/practice?mode=starred${bankQuery}` });
  },

  memorizeStar() {
    const { filterBankId, starList } = this.data;
    if (!starList.length) return;
    const bankQuery = filterBankId ? `&bank_id=${filterBankId}` : '';
    wx.navigateTo({ url: `/pages/practice/practice?mode=memorize&source=starred${bankQuery}` });
  },
});
