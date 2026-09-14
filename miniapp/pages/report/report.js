const { request } = require('../../utils/request');

Page({
  data: {
    loading: true,
    report: null,
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
    this.setData({ loading: true });
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
    } catch {
      this.setData({ loading: false });
    }
  },
});
