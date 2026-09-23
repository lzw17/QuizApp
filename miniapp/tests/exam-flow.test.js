'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function loadExamPage(mocks) {
  const filename = path.join(__dirname, '..', 'pages/exam/exam.js');
  const source = fs.readFileSync(filename, 'utf8');
  let definition = null;
  const sandbox = {
    console,
    Date,
    clearInterval: mocks.clearInterval || (() => {}),
    setInterval: mocks.setInterval || (() => 1),
    clearTimeout: mocks.clearTimeout || (() => {}),
    setTimeout: mocks.setTimeout || (() => 1),
    getApp: () => ({}),
    Page: page => { definition = page; },
    wx: mocks.wx,
    require: request => {
      if (request === '../../utils/request') return mocks.requestModule;
      throw new Error(`Unexpected require: ${request}`);
    },
  };
  vm.runInNewContext(source, sandbox, { filename });
  definition.data = JSON.parse(JSON.stringify(definition.data));
  definition.setData = function setData(update, callback) {
    Object.assign(this.data, update);
    if (callback) callback();
  };
  return definition;
}

async function testServerDurationDrivesCountdown() {
  const question = {
    id: 1,
    bank_id: 7,
    type: 'single',
    content: 'question',
    options: [{ key: 'A', text: 'answer' }],
  };
  const page = loadExamPage({
    requestModule: {
      getUserId: async () => 1,
      request: async options => {
        assert.equal(options.url, '/api/exam/start');
        return { session_id: 'session-1', duration_seconds: 1200, questions: [question] };
      },
    },
    wx: { showLoading: () => {}, hideLoading: () => {}, showToast: () => {} },
  });
  page.data.bankId = 7;
  await page.startExam();
  assert.equal(page.data.timeLeft, 1200);
  assert.equal(page.data.examMinutes, 20);
  assert.equal(page.data.sessionId, 'session-1');
  assert.ok(page._deadlineMs > Date.now());
  page._clearTimer();
}

function testExpiredTimerSubmitsWithoutModal() {
  let submitCount = 0;
  let toastCount = 0;
  const page = loadExamPage({
    requestModule: { getUserId: async () => 1, request: async () => ({}) },
    wx: { showToast: () => { toastCount += 1; } },
  });
  page.data.phase = 'exam';
  page.data.timeLeft = 1;
  page._deadlineMs = Date.now() - 1;
  page._doSubmit = () => { submitCount += 1; };

  assert.equal(page._syncTimer(), false);
  assert.equal(page.data.timeLeft, 0);
  assert.equal(submitCount, 1);
  assert.equal(toastCount, 1);
  page._syncTimer();
  assert.equal(submitCount, 1);
}

function testSelectedOptionsPersistAcrossQuestionNavigation() {
  const page = loadExamPage({
    requestModule: { getUserId: async () => 1, request: async () => ({}) },
    wx: {},
  });
  page._questions = [
    { id: 1, type: 'single', options: [{ key: 'A' }, { key: 'B' }] },
    { id: 2, type: 'multi', options: [{ key: 'A' }, { key: 'B' }] },
  ];
  page.data.userAnswers = ['', ''];
  page._showQuestion(0);
  page.selectOption({ currentTarget: { dataset: { key: 'B' } } });
  assert.equal(page.data.userAnswers[0], 'B');
  assert.equal(page.data.selectedKeys.B, true);

  page.nextQ();
  assert.equal(Object.keys(page.data.selectedKeys).length, 0);
  page.selectOption({ currentTarget: { dataset: { key: 'A' } } });
  page.selectOption({ currentTarget: { dataset: { key: 'B' } } });
  assert.equal(page.data.userAnswers[1], 'AB');
  assert.equal(page.data.selectedKeys.A, true);
  assert.equal(page.data.selectedKeys.B, true);

  page.prevQ();
  assert.equal(page.data.selectedKeys.B, true);
  assert.equal(Boolean(page.data.selectedKeys.A), false);
  page.data.showSheet = true;
  page.jumpTo({ currentTarget: { dataset: { index: 1 } } });
  assert.equal(page.data.showSheet, false);
  assert.equal(page.data.selectedKeys.A, true);
  assert.equal(page.data.selectedKeys.B, true);
}

async function testExpiredSubmissionRetriesAfterSubmittingIsReleased() {
  const scheduled = [];
  const toasts = [];
  let requests = 0;
  const page = loadExamPage({
    requestModule: {
      getUserId: async () => 1,
      request: async () => {
        requests += 1;
        throw new Error('offline');
      },
    },
    setTimeout: callback => {
      scheduled.push(callback);
      return scheduled.length;
    },
    wx: {
      showLoading: () => {},
      hideLoading: () => {},
      showToast: options => toasts.push(options.title),
    },
  });
  page.data.phase = 'exam';
  page.data.bankId = 7;
  page.data.sessionId = 'session-retry';
  page.data.examMinutes = 10;
  page.data.userAnswers = [''];
  page._questions = [{ id: 1 }];
  page._deadlineMs = Date.now() - 1;
  page._pageVisible = true;

  page._handleTimeExpired();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(requests, 1);
  assert.equal(page.data.submitting, false);
  assert.equal(page._autoSubmitTriggered, false);
  assert.equal(scheduled.length, 1);

  scheduled.shift()();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(requests, 2);
  assert.equal(scheduled.length, 1);
  assert.equal(toasts.filter(title => title.includes('考试时间已结束')).length, 1);

  scheduled.shift()();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(requests, 3);
  assert.equal(scheduled.length, 0);
  assert.ok(toasts.includes('自动交卷失败，请点击交卷重试'));
}

async function main() {
  await testServerDurationDrivesCountdown();
  testExpiredTimerSubmitsWithoutModal();
  testSelectedOptionsPersistAcrossQuestionNavigation();
  await testExpiredSubmissionRetriesAfterSubmittingIsReleased();
  console.log('miniapp exam flow tests passed');
}

main().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
