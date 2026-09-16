'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function loadPage(relativePath, mocks) {
  const filename = path.join(__dirname, '..', relativePath);
  const source = fs.readFileSync(filename, 'utf8');
  let definition = null;
  const sandbox = {
    console,
    clearTimeout,
    setTimeout,
    getApp: () => mocks.app || {},
    Page: page => { definition = page; },
    wx: mocks.wx || {},
    require: request => {
      if (request === '../../utils/request') return mocks.requestModule;
      throw new Error(`Unexpected require: ${request}`);
    },
  };
  vm.runInNewContext(source, sandbox, { filename });
  assert.ok(definition, `Page was not registered: ${relativePath}`);
  definition.data = JSON.parse(JSON.stringify(definition.data));
  definition.setData = function setData(update, callback) {
    Object.assign(this.data, update);
    if (callback) callback();
  };
  return definition;
}

function testWrongBookUsesGlobalReviewRoutes() {
  const navigations = [];
  const page = loadPage('pages/wrong-book/wrong-book.js', {
    requestModule: { request: async () => [], getUserId: async () => 1 },
    wx: {
      navigateTo: options => navigations.push(options.url),
      showToast: () => { throw new Error('Cross-bank review must not require a bank filter'); },
    },
  });
  page.data.wrongList = [{ bank_id: 11 }, { bank_id: 22 }];
  page.data.starList = [{ bank_id: 11 }, { bank_id: 22 }];
  page.data.filterBankId = '';

  page.practiceWrong();
  page.memorizeWrong();
  page.practiceStar();
  page.memorizeStar();

  assert.deepEqual(navigations, [
    '/pages/practice/practice?mode=wrong',
    '/pages/practice/practice?mode=memorize&source=wrong',
    '/pages/practice/practice?mode=starred',
    '/pages/practice/practice?mode=memorize&source=starred',
  ]);
}

async function testPracticeUsesQuestionBankId() {
  const calls = [];
  const question = {
    id: 101,
    bank_id: 22,
    type: 'single',
    content: 'question',
    options: [{ key: 'A', text: 'answer' }],
    tags: [],
    difficulty: 1,
  };
  const request = async options => {
    calls.push(options);
    if (options.url.startsWith('/api/questions?')) return [question];
    if (options.url.startsWith('/api/questions/count?')) return { total: 1 };
    if (options.url === '/api/answer') {
      return { is_correct: true, correct_answer: 'A', explanation: '', correct_rate: 1 };
    }
    if (options.url === '/api/star') return { is_starred: true };
    if (options.url === '/api/starred-questions') return [];
    throw new Error(`Unexpected request: ${options.url}`);
  };
  const page = loadPage('pages/practice/practice.js', {
    app: {},
    requestModule: { request, getUserId: async () => 1 },
    wx: { showToast: () => {} },
  });
  page.data.bankId = null;
  page.data.mode = 'wrong';

  await page._loadQuestions(0);
  const questionRequest = calls.find(call => call.url.startsWith('/api/questions?'));
  const countRequest = calls.find(call => call.url.startsWith('/api/questions/count?'));
  assert.ok(questionRequest);
  assert.ok(countRequest);
  assert.equal(questionRequest.url.includes('bank_id='), false);
  assert.equal(countRequest.url.includes('bank_id='), false);

  page.setData({ selectedAnswer: 'A' });
  await page.confirmAnswer();
  await page.toggleStar();
  const answerRequest = calls.find(call => call.url === '/api/answer');
  const starRequest = calls.find(call => call.url === '/api/star');
  assert.equal(answerRequest.data.bank_id, 22);
  assert.equal(starRequest.data.bank_id, 22);
}

async function main() {
  testWrongBookUsesGlobalReviewRoutes();
  await testPracticeUsesQuestionBankId();
  console.log('miniapp review flow tests passed');
}

main().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
