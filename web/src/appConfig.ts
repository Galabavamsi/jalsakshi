import { readConfig } from './config';

/** The configuration this build was made with. */
export const appConfig = readConfig(import.meta.env);

export const isMock = appConfig.mode === 'mock';
