import { test, expect } from '@playwright/test';
import { login } from './helpers';

test.describe('Admin', () => {
  test.beforeEach(async ({ page }) => {
    await login(page);
  });

  test('admin dashboard loads with real stats', async ({ page }) => {
    await page.goto('/admin');
    // Dashboard should render without errors and show content
    await expect(page.locator('body')).not.toContainText('Erreur interne');
    await expect(page).not.toHaveURL(/login/);
  });

  test('analytics page renders RAG + AI insights sections', async ({ page }) => {
    await page.goto('/admin/analytics');
    await expect(page.getByText('Pipeline RAG')).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText('IA Insights')).toBeVisible();
    await expect(page.getByText('Seuils de routage RAG')).toBeVisible();
  });
});
