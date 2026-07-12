import { test, expect } from '@playwright/test';
import { login, ADMIN_EMAIL } from './helpers';

test.describe('Authentication', () => {
  test('rejects invalid credentials', async ({ page }) => {
    await page.goto('/login');
    await page.locator('input[type="email"]').fill(ADMIN_EMAIL);
    await page.locator('input[type="password"], input[type="text"].password-input').first().fill('WrongPassword123!');
    await page.locator('button[type="submit"]').click();
    // Stays on login and shows an error — never reaches the chat
    await expect(page).toHaveURL(/login/);
    await expect(page.locator('textarea.message-input')).toHaveCount(0);
  });

  test('logs in with valid credentials and reaches the chat', async ({ page }) => {
    await login(page);
    await expect(page).not.toHaveURL(/login/);
  });

  test('unauthenticated access to /chat redirects to login', async ({ page }) => {
    await page.goto('/chat');
    await expect(page).toHaveURL(/login/, { timeout: 15_000 });
  });
});
