const { pollTask } = require('../../utils/request');

Page({
  data: {
    taskId: '',
    bankId: null,
    bankName: '',
    progress: 0,
    status: 'pending',
    message: '',
    generatedCount: 0,
    error: '',
  },

  _stopPoll: null,

  onLoad(options) {
    const { task_id, bank_id, bank_name } = options;
    this.setData({
      taskId: task_id,
      bankId: parseInt(bank_id),
      bankName: decodeURIComponent(bank_name || ''),
    });
    this._startPolling(task_id);
  },

  _startPolling(taskId) {
    this._stopPoll = pollTask(
      taskId,
      (data) => {
        this.setData({
          progress: data.progress || 0,
          status: data.status,
          message: data.message || '',
          generatedCount: data.generated_count || 0,
          error: data.error || '',
        });
      },
      (data) => {
        this.setData({
          progress: 100,
          status: 'done',
          generatedCount: data.generated_count || 0,
          message: '题库生成完成！',
        });
      },
      (errMsg) => {
        this.setData({ status: 'failed', error: errMsg });
      },
    );
  },

  onUnload() {
    if (this._stopPoll) this._stopPoll();
  },

  goDetail() {
    wx.redirectTo({
      url: `/pages/bank-detail/bank-detail?id=${this.data.bankId}`,
    });
  },

  goBack() {
    wx.navigateBack();
  },
});
