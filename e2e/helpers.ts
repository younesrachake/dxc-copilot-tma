import { Page, expect } from '@playwright/test';

export const ADMIN_EMAIL = 'admin@dxc.com';
export const ADMIN_PASSWORD = process.env.E2E_ADMIN_PASSWORD || 'E2eAdminPass1234!';

export async function login(page: Page, email = ADMIN_EMAIL, password = ADMIN_PASSWORD): Promise<void> {
  await page.goto('/login');
  await page.locator('input[type="email"]').fill(email);
  await page.locator('input[type="password"], input[type="text"].password-input').first().fill(password);
  await page.locator('button[type="submit"]').click();
  // Successful login lands on the chat view
  await expect(page.locator('textarea.message-input')).toBeVisible({ timeout: 15_000 });
}
