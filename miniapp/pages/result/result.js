Page({
  data: {
    result: null,
    wrongItems: [],
    bankId: null,
    typeLabel: { single: '单选', multi: '多选', judge: '判断' },
  },

  onLoad(options) {
    let result = null;
    try {
      if (options.result_key) result = wx.getStorageSync(decodeURIComponent(options.result_key));
      if (!result && options.data) result = JSON.parse(decodeURIComponent(options.data));
    } catch (error) {
      result = null;
    }
    if (options.result_key) wx.removeStorageSync(decodeURIComponent(options.result_key));
    if (!result || typeof result !== 'object') {
      wx.showToast({ title: '结果已失效，请重新考试', icon: 'none' });
      setTimeout(() => wx.navigateBack({ delta: 1 }), 500);
      return;
    }
    const bankId = parseInt(options.bank_id);

    // 整理错题详情
    const wrongItems = (result.results || [])
      .filter(r => !r.is_correct)
      .map(r => ({
        question_id: r.question_id,
        content: r.content || '',
        type: r.type || 'single',
        user_answer: r.user_answer,
        correct_answer: r.correct_answer,
        explanation: r.explanation,
      }));

    this.setData({ result, wrongItems, bankId });
    wx.setNavigationBarTitle({ title: result.passed ? '考试通过 ✓' : '考试结果' });
  },

  goBack() { wx.navigateBack({ delta: 1 }); },

  reviewWrong() {
    if (this.data.bankId) {
      wx.setStorageSync('wrongBookFilterBankId', this.data.bankId);
    }
    wx.switchTab({ url: '/pages/wrong-book/wrong-book' });
  },
});
