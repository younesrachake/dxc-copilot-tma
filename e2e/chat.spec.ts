import { test, expect } from '@playwright/test';
import { login } from './helpers';

test.describe('Chat', () => {
  test.beforeEach(async ({ page }) => {
    await login(page);
  });

  test('sends a message and receives a bot reply (LLM simulation mode)', async ({ page }) => {
    const input = page.locator('textarea.message-input');
    await input.fill('Comment redémarrer un service TMA en production ?');
    await input.press('Enter');

    // User bubble appears immediately
    await expect(page.locator('.message.user-message').last()).toContainText('redémarrer un service');

    // Bot reply arrives (fallback response without API keys — deterministic)
    await expect(page.locator('.message.bot-message').last()).toBeVisible({ timeout: 30_000 });
    const botText = await page.locator('.message.bot-message').last().innerText();
    expect(botText.length).toBeGreaterThan(10);
  });

  test('new conversation appears in the sidebar history', async ({ page }) => {
    const input = page.locator('textarea.message-input');
    const marker = `session e2e ${Date.now()}`;
    await input.fill(marker);
    await input.press('Enter');
    await expect(page.locator('.message.bot-message').last()).toBeVisible({ timeout: 30_000 });

    // The session title (first 50 chars of the message) shows up in the history list
    await expect(page.locator('.history-list')).toContainText('session e2e', { timeout: 15_000 });
  });

  test('semantic search box is present in the sidebar', async ({ page }) => {
    await expect(page.locator('.conv-search-input')).toBeVisible();
  });
});
