// Placeholder with the agreed API; replaced by the real discovery module at merge.
import type { EngineChoice } from '../engine/model-policy.js';

export interface DiscoveredModel { id: string; label: string; efforts: string[] }
export interface DiscoveredCatalog {
  engine: EngineChoice;
  models: DiscoveredModel[];
  cliDefault?: { model: string; effort?: string };
  excluded: { id: string; reason: 'hidden' | 'no-effort' }[];
  cliVersion?: string;
}
export interface DiscoveryOptions { cwd: string; timeoutMs?: number; env?: NodeJS.ProcessEnv }
export class ModelDiscoveryError extends Error { constructor(readonly code: 'spawn' | 'timeout' | 'protocol' | 'empty', message: string) { super(message); } }

export function discoverCodexModels(_command: string, _options: DiscoveryOptions): Promise<DiscoveredCatalog> {
  return Promise.reject(new ModelDiscoveryError('spawn', 'not implemented'));
}
export function discoverClaudeModels(_command: string, _options: DiscoveryOptions): Promise<DiscoveredCatalog> {
  return Promise.reject(new ModelDiscoveryError('spawn', 'not implemented'));
}
export function discoverModels(_engine: EngineChoice, _command: string, _options: DiscoveryOptions): Promise<DiscoveredCatalog> {
  return Promise.reject(new ModelDiscoveryError('spawn', 'not implemented'));
}
export function mapCodexModels(_data: unknown[]): Pick<DiscoveredCatalog, 'models' | 'cliDefault' | 'excluded'> {
  throw new ModelDiscoveryError('spawn', 'not implemented');
}
export function mapClaudeModels(_models: unknown[]): Pick<DiscoveredCatalog, 'models' | 'cliDefault' | 'excluded'> {
  throw new ModelDiscoveryError('spawn', 'not implemented');
}
