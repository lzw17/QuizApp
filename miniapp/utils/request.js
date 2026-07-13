const app = getApp();

function request(options) {
  return app.ensureLogin().then(() => _request(options, false));
}

function _request(options, retried) {
  const token = app.globalData.accessToken;
  return new Promise((resolve, reject) => {
    wx.request({
      url: `${app.globalData.baseUrl}${options.url}`,
      method: options.method || 'GET',
      data: options.data || {},
      header: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...(options.header || {}),
      },
      success(res) {
        if (res.statusCode >= 200 && res.statusCode < 300) {
          resolve(res.data);
        } else if (res.statusCode === 401 && token && !retried) {
          app.clearSession();
          app.wxLogin({ force: true })
            .then(() => _request(options, true))
            .then(resolve)
            .catch(error => {
              wx.showToast({ title: error.message || '登录已失效，请重新登录', icon: 'none' });
              reject(error);
            });
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
  if (app.globalData.userId) return Promise.resolve(app.globalData.userId);
  if (typeof app.ensureLogin === 'function') {
    return app.ensureLogin().then(user => user && user.id);
  }
  return Promise.resolve(null);
}

/** 上传文件（multipart/form-data） */
function uploadFile(filePath, formData = {}, options = {}) {
  return app.ensureLogin().then(() => _uploadFile(filePath, formData, options, false));
}

function _uploadFile(filePath, formData, options, retried) {
  const token = app.globalData.accessToken;
  return new Promise((resolve, reject) => {
    wx.uploadFile({
      url: `${app.globalData.baseUrl}${options.url || '/api/upload'}`,
      filePath,
      name: options.name || 'file',
      formData,
      header: token ? { Authorization: `Bearer ${token}` } : {},
      success(res) {
        let data;
        try {
          data = typeof res.data === 'string' ? JSON.parse(res.data) : res.data;
        } catch {
          reject(new Error('服务器响应格式错误'));
          return;
        }
        if (res.statusCode >= 200 && res.statusCode < 300) {
          resolve(data);
        } else if (res.statusCode === 401 && token && !retried) {
          app.clearSession();
          app.wxLogin({ force: true })
            .then(() => _uploadFile(filePath, formData, options, true))
            .then(resolve)
            .catch(error => {
              wx.showToast({ title: error.message || '登录已失效，请重新登录', icon: 'none' });
              reject(error);
            });
        } else {
          const msg = (data && data.detail) || `上传失败 (${res.statusCode})`;
          wx.showToast({ title: msg, icon: 'none' });
          reject(new Error(msg));
        }
      },
      fail() {
        const error = new Error('网络错误，请检查连接');
        wx.showToast({ title: error.message, icon: 'none' });
        reject(error);
      },
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
