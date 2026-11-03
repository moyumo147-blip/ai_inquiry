// scripts/ui-smoke.mjs
// 前端端到端冒烟：用系统 Edge（playwright-core channel）登录 → 新建问诊 → 发消息 → 截图。
// 前置：后端 8000、前端 dev 5173 已启动，且已运行 scripts/seed_demo.py。
//
// 运行：
//   node scripts/ui-smoke.mjs

import { mkdirSync } from 'node:fs'
import { chromium } from 'playwright-core'

const BASE = process.env.UI_BASE || 'http://127.0.0.1:5173'
const SHOTS = 'shots'
mkdirSync(SHOTS, { recursive: true })

const errors = []

const browser = await chromium.launch({
  channel: 'msedge',
  headless: true,
  args: ['--disable-gpu', '--no-sandbox'],
})

const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
page.on('console', (msg) => {
  if (msg.type() === 'error') errors.push(`console: ${msg.text()}`)
})
page.on('pageerror', (err) => errors.push(`pageerror: ${err.message}`))

async function step(name, fn) {
  process.stdout.write(`▶ ${name} ... `)
  try {
    await fn()
    console.log('OK')
  } catch (error) {
    console.log('FAIL')
    errors.push(`${name}: ${error.message.split('\n')[0]}`)
  }
}

await step('打开登录页', async () => {
  await page.goto(`${BASE}/login`, { waitUntil: 'networkidle' })
  await page.getByPlaceholder('请输入用户名').fill('demo')
  await page.getByPlaceholder('请输入密码').fill('demo123456')
})

await step('登录', async () => {
  await page.getByRole('button', { name: '登录' }).click()
  await page.waitForURL(`${BASE}/`, { timeout: 20000 })
  await page.waitForTimeout(1200)
  await page.screenshot({ path: `${SHOTS}/01-dashboard.png` })
})

await step('进入问诊页', async () => {
  await page.goto(`${BASE}/consult`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(800)
})

await step('新建问诊（分诊）', async () => {
  const box = page.getByPlaceholder(/例如：孩子/)
  if (await box.count()) {
    await box.fill('孩子8岁，上课坐不住、注意力不集中，写作业拖拉，怀疑多动症')
    await page.getByRole('button', { name: '开始问诊' }).click()
    await page.waitForTimeout(6000)
  }
  await page.screenshot({ path: `${SHOTS}/02-consult-triage.png` })
})

await step('发送问诊消息（SSE）', async () => {
  const composer = page.getByPlaceholder(/描述症状或继续追问/)
  const before = await page.locator('.chat-bubble.assistant').count()
  await composer.fill('需要做哪些检查？平时在家怎么训练注意力？')
  await composer.press('Enter')
  // 等待新的助手气泡出现，并且流式真正结束（底部提示恢复为免责声明）
  await page.waitForFunction(
    (n) => {
      const bubbles = document.querySelectorAll('.chat-bubble.assistant')
      const foot = document.querySelector('.composer-foot .small')
      return bubbles.length > n && !!foot && foot.textContent.includes('AI 生成内容仅供参考')
    },
    before,
    { timeout: 180000 },
  )
  await page.waitForTimeout(1200)
  await page.screenshot({ path: `${SHOTS}/03-consult-answer.png` })
})

await step('打开病历页', async () => {
  await page.goto(`${BASE}/records`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(1000)
  await page.screenshot({ path: `${SHOTS}/04-records.png` })
})

await step('打开病例库并语义检索', async () => {
  await page.goto(`${BASE}/cases`, { waitUntil: 'networkidle' })
  await page.getByRole('tab', { name: '语义检索（向量）' }).click()
  await page.getByPlaceholder(/用一句话描述/).fill('孩子注意力不集中、坐不住')
  await page.getByRole('button', { name: '语义检索' }).click()
  await page.waitForTimeout(3000)
  await page.screenshot({ path: `${SHOTS}/05-cases.png` })
})

await browser.close()

if (errors.length) {
  console.log(`\n❌ UI 冒烟失败 ${errors.length} 项：`)
  for (const e of errors) console.log('  -', e)
  process.exit(1)
}
console.log('\n🎉 UI 冒烟通过，截图已保存到 shots/')
