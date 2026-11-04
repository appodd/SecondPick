import { fireEvent, render, screen } from '@testing-library/react';
import { expect, it, vi } from 'vitest';
import { EnginePanel } from './SystemPanels';
import { serviceStates, type SystemState, type ServiceState } from './systemState';

it('explains a fresh installation and exposes preparation instructions without executing installation', () => {
  const result = { ready: false, checked_at: new Date().toISOString(), checks: [{ code: 'configuration', ok: true }, { code: 'source', ok: false }] };
  const mutate = vi.fn();
  const system = { engine: { data: { result }, isError: false }, states: serviceStates(undefined, undefined, result),
    action: { isPending: false, mutate }, observe: (state: ServiceState) => state, observedAt: { engine: Date.now() },
  } as unknown as SystemState;
  render(<EnginePanel system={system} />);
  expect(screen.getByText('采集引擎尚未安装')).toBeVisible();
  expect(screen.getByText('未安装')).toBeVisible();
  expect(screen.queryByText('引擎版本兼容性')).toBeNull();
  expect(screen.getByText('python scripts/setup_monitor.py')).toBeVisible();
  expect(screen.getByText(/先停止当前工作台/)).toBeVisible();
  expect(screen.getByRole('link', { name: '完整安装与修复说明' })).toHaveAttribute('href', expect.stringContaining('user-guide.md'));
  expect(mutate).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: '检查采集引擎环境' }));
  expect(mutate).toHaveBeenCalledWith('engine');
});

it.each(['revision', 'python', 'dependencies', 'browser', 'probe'])('keeps %s failures distinct from missing installation', code => {
  const state = serviceStates(undefined, undefined, { ready: false, checked_at: '', checks: [{ code, ok: false }] }).collection;
  expect(state.label).not.toBe('采集引擎尚未安装');
  expect(state.tone).toBe('warn');
  expect(state.detail).not.toBe('');
});
