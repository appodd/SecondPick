import { act, cleanup, renderHook } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, expect, it, vi } from 'vitest';
import type { ReactNode } from 'react';
import { useSystemState } from './systemState';

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it.each(['basic', 'ai', 'failure'] as const)('completion persists %s without issuing research or collection requests', async mode => {
  const settings = { setup_completed: false, setup_mode: 'basic', default_city: null, platforms: ['xianyu'], allow_ocr: true, preferred_view: 'research' };
  const cache = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  cache.setQueryData(['settings'], settings);
  cache.setQueryData(['setup-status'], { environment: [], codex: { cli_available: false }, xianyu: {} });
  cache.setQueryData(['system-health'], { status: 'ok' });
  cache.setQueryData(['browser-status'], { auth_status: 'verified', active_job: null });
  cache.setQueryData(['system-engine'], { result: { ready: true, checked_at: new Date().toISOString() } });
  const fetch = vi.fn().mockImplementation(async () => mode === 'failure'
    ? new Response(JSON.stringify({ error: { code: 'save_failed', message: 'Save failed' } }), { status: 500 })
    : new Response(JSON.stringify({ ...settings, setup_completed: true, setup_mode: mode })));
  vi.stubGlobal('fetch', fetch);
  const { result } = renderHook(useSystemState, { wrapper: ({ children }: { children: ReactNode }) => <QueryClientProvider client={cache}>{children}</QueryClientProvider> });
  const selectedMode = mode === 'failure' ? 'basic' : mode;
  await act(async () => {
    const completion = result.current.action.mutateAsync({ kind: 'complete', setupMode: selectedMode });
    if (mode === 'failure') await expect(completion).rejects.toThrow();
    else await completion;
  });
  expect(fetch).toHaveBeenCalledTimes(1);
  expect(String(fetch.mock.calls[0][0])).toContain('/api/settings');
  expect(fetch.mock.calls[0][1].method).toBe('PATCH');
  expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual({ setup_completed: true, setup_mode: selectedMode });
  expect(cache.getQueryData(['settings'])).toMatchObject(mode === 'failure' ? settings : { setup_completed: true, setup_mode: mode });
});
