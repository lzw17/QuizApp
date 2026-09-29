const { request, getUserId } = require('../../utils/request');
const app = getApp();

const share = require('../../utils/share');

Page({
  onShareAppMessage() { return share.shareApp(this); },
  onShareTimeline() { return share.shareTimeline(this); },
  data: { bankId: null, bank: null, tags: [], progress: {}, statusBarHeight: 0, loadError: '' },

  onLoad(options) {
    const { statusBarHeight } = wx.getWindowInfo();
    const id = parseInt(options.id);
    this.setData({ bankId: id, statusBarHeight });
    this._load(id);
  },

  onShow() {
    if (this.data.bankId) this._loadProgress();
  },

  async _load(id) {
    this.setData({ loadError: '' });
    try {
      const [bank, tags] = await Promise.all([
        request({ url: `/api/banks/${id}` }),
        request({ url: `/api/banks/${id}/tags` }),
      ]);
      this.setData({ bank, tags });
      wx.setNavigationBarTitle({ title: bank.name });
      this._loadProgress();
    } catch (error) {
      // 失败必须有明确出口，否则模板只有一个「非 bank 即加载中」的分支 → 永久转圈
      this.setData({
        loadError: error && error.needLogin ? '登录后即可查看题库' : '题库加载失败，请稍后重试',
      });
    }
  },

  retryLoad() {
    if (this.data.bankId) this._load(this.data.bankId);
  },

  async _loadProgress() {
    const uid = await getUserId();
    if (!uid || !this.data.bankId) return;
    try {
      const p = await request({ url: `/api/progress/${this.data.bankId}` });
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

  goBack() {
    wx.navigateBack();
  },
});
