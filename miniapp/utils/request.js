const app = getApp();

function request(options) {
  return new Promise((resolve, reject) => {
    wx.request({
      url: `${app.globalData.baseUrl}${options.url}`,
      method: options.method || 'GET',
      data: options.data || {},
      header: {
        'Content-Type': 'application/json',
        ...(options.header || {}),
      },
      success(res) {
        if (res.statusCode >= 200 && res.statusCode < 300) {
          resolve(res.data);
        } else {
          const msg = (res.data && res.data.detail) || `请求失败 (${res.statusCode})`;
          wx.showToast({ title: msg, icon: 'none' });
          reject(new Error(msg));
        }
      },
      fail(err) {
        wx.showToast({ title: '网络错误，请检查连接', icon: 'none' });
        reject(err);
      },
    });
  });
}

function getUserId() {
  const cached = app.globalData.userId || (wx.getStorageSync('userInfo') || {}).id;
  if (cached) return Promise.resolve(cached);
  if (typeof app.ensureLogin === 'function') {
    return app.ensureLogin().then(user => user && user.id);
  }
  return Promise.resolve(null);
}

/** 上传文件（multipart/form-data） */
function uploadFile(filePath, formData = {}) {
  return new Promise((resolve, reject) => {
    wx.uploadFile({
      url: `${app.globalData.baseUrl}/api/upload`,
      filePath,
      name: 'file',
      formData,
      success(res) {
        const data = typeof res.data === 'string' ? JSON.parse(res.data) : res.data;
        if (res.statusCode >= 200 && res.statusCode < 300) {
          resolve(data);
        } else {
          const msg = (data && data.detail) || `上传失败 (${res.statusCode})`;
          wx.showToast({ title: msg, icon: 'none' });
          reject(new Error(msg));
        }
      },
      fail: reject,
    });
  });
}

/** SSE 进度轮询（小程序不支持原生 SSE，改用定时轮询）*/
function pollTask(taskId, onProgress, onDone, onError) {
  let timer = null;
  let stopped = false;

  function poll() {
    if (stopped) return;
    request({ url: `/api/task/${taskId}` }).then(data => {
      if (stopped) return;
      onProgress && onProgress(data);
      if (data.status === 'done') {
        stopped = true;
        onDone && onDone(data);
      } else if (data.status === 'failed') {
        stopped = true;
        onError && onError(data.error || '生成失败');
      } else {
        timer = setTimeout(poll, 1500);
      }
    }).catch(() => {
      if (!stopped) {
        timer = setTimeout(poll, 3000);
      }
    });
  }

  poll();
  return () => { stopped = true; clearTimeout(timer); };
}

module.exports = { request, uploadFile, pollTask, getUserId };
