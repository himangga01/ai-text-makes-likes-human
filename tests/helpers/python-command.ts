import { resolvePythonCommand } from '../../scripts/python-command.mjs';

/** Python for tests that spawn the real engine; see scripts/python-command.mjs for the lookup order. */
export const pythonCommand: string = resolvePythonCommand();

/** Office document tests also need lxml; undefined lets a suite skip instead of failing on a bare interpreter. */
export const documentPythonCommand: string | undefined = resolvePythonCommand({ modules: ['lxml'], optional: true });
