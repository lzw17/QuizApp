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
    this._loadAll();
  },

  onShow() {
    // 更新自定义 tabBar 选中状态
    if (typeof this.getTabBar === 'function' && this.getTabBar()) {
      this.getTabBar().setData({ selected: 1 });
    }
    this._loadAll();
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

  async _loadAll() {
    await this._loadBanks();
    await this._loadWrong();
    if (this.data.activeTab === 'star') {
      await this._loadStars();
    }
  },

  async _loadWrong() {
    const uid = await getUserId();
    if (!uid) return;
    try {
      let url = '/api/wrong-questions';
      if (this.data.filterBankId) url += `?bank_id=${this.data.filterBankId}`;
      const list = await request({ url });
      this.setData({ wrongList: list.map(item => ({
        ...item,
        answered_at: item.answered_at ? item.answered_at.slice(0, 10) : '',
      })) });
    } catch {}
  },

  async _loadStars() {
    const uid = await getUserId();
    if (!uid) return;
    const { banks } = this.data;
    const starQuestions = [];
    for (const bank of banks) {
      try {
        const p = await request({ url: `/api/progress/${bank.id}` });
        if (p.starred_ids && p.starred_ids.length > 0) {
          for (const qid of p.starred_ids) {
            try {
              const q = await request({ url: `/api/questions/${qid}` });
              starQuestions.push({ ...q, bank_id: bank.id });
            } catch {}
          }
        }
      } catch {}
    }
    this.setData({ starList: starQuestions });
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
    const bankId = filterBankId || wrongList[0].bank_id;
    wx.navigateTo({ url: `/pages/practice/practice?bank_id=${bankId}&mode=wrong` });
  },

  practiceStar() {
    const { starList } = this.data;
    if (!starList.length) return;
    wx.navigateTo({ url: `/pages/practice/practice?bank_id=${starList[0].bank_id}&mode=starred` });
  },
});
