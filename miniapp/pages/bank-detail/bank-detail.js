const { request } = require('../../utils/request');
const app = getApp();

Page({
  data: { bankId: null, bank: null, tags: [], progress: {} },

  onLoad(options) {
    const id = parseInt(options.id);
    this.setData({ bankId: id });
    this._load(id);
  },

  onShow() {
    if (this.data.bankId) this._loadProgress();
  },

  async _load(id) {
    try {
      const [bank, tags] = await Promise.all([
        request({ url: `/api/banks/${id}` }),
        request({ url: `/api/banks/${id}/tags` }),
      ]);
      this.setData({ bank, tags });
      wx.setNavigationBarTitle({ title: bank.name });
      this._loadProgress();
    } catch {}
  },

  async _loadProgress() {
    const uid = app.globalData.userId;
    if (!uid || !this.data.bankId) return;
    try {
      const p = await request({ url: `/api/progress/${this.data.bankId}?user_id=${uid}` });
      this.setData({ progress: p });
    } catch {}
  },

  startPractice(e) {
    const mode = e.currentTarget.dataset.mode;
    const skip = mode === 'sequential' ? this.data.progress.last_position || 0 : 0;
    wx.navigateTo({
      url: `/pages/practice/practice?bank_id=${this.data.bankId}&mode=${mode}&skip=${skip}`,
    });
  },

  startByTag(e) {
    const tag = e.currentTarget.dataset.tag;
    wx.navigateTo({
      url: `/pages/practice/practice?bank_id=${this.data.bankId}&mode=tag&tag=${encodeURIComponent(tag)}`,
    });
  },

  startExam() {
    wx.navigateTo({
      url: `/pages/exam/exam?bank_id=${this.data.bankId}`,
    });
  },
});
