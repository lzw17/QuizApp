const { request } = require('../../utils/request');

const share = require('../../utils/share');

Page({
  onShareAppMessage() { return share.shareApp(this); },
  onShareTimeline() { return share.shareTimeline(this); },
  data: {
    loading: true,
    report: null,
    loadError: '',
  },

  onLoad() {
    this._loadReport();
  },

  onShow() {
    if (this.data.report) this._loadReport();
  },

  onPullDownRefresh() {
    this._loadReport().finally(() => wx.stopPullDownRefresh());
  },

  async _loadReport() {
    this.setData({ loading: true, loadError: '' });
    try {
      const report = await request({ url: '/api/study-report?days=7' });
      const maxTotal = Math.max(1, ...(report.daily || []).map(item => item.total));
      const daily = (report.daily || []).map(item => ({
        ...item,
        dayLabel: item.date.slice(5),
        accuracyText: `${Math.round(item.accuracy * 100)}%`,
        barHeight: Math.max(8, Math.round(item.total / maxTotal * 180)),
      }));
      const todayTotal = daily.length ? daily[daily.length - 1].total : 0;
      this.setData({ report: { ...report, daily, todayTotal }, loading: false });
    } catch (error) {
      // 失败必须落到明确的错误态，否则模板两个分支（report / loading）都不成立 → 白屏
      this.setData({
        loading: false,
        loadError: error && error.needLogin ? '登录后即可查看学习报告' : '报告加载失败，请稍后重试',
      });
    }
  },

  retryLoad() {
    this._loadReport();
  },
});
