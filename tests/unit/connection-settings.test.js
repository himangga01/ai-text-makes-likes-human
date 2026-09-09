import { it,expect } from 'vitest';
import { connectionState,formatElapsed } from '../../public/connection-settings.js';
it('connection state distinguishes pending, authenticated, missing login and failed CLI',()=>{
  expect(connectionState().state).toBe('checking');
  expect(connectionState({ready:true}).state).toBe('ready');
  expect(connectionState({ready:false,installed:true,authenticated:false}).state).toBe('auth');
  expect(connectionState({ready:false,installed:false}).state).toBe('error');
  expect(connectionState({ready:false,installed:true,authenticated:false,reason:'unsupported-version'}).label).toBe('CLI 업데이트 필요');
});
it('elapsed time supports seconds, long runs and negative clock values',()=>{
  expect(formatElapsed(0)).toBe('00:00');expect(formatElapsed(59999)).toBe('00:59');
  expect(formatElapsed(61000)).toBe('01:01');expect(formatElapsed(3661000)).toBe('1:01:01');expect(formatElapsed(-1)).toBe('00:00');
});
