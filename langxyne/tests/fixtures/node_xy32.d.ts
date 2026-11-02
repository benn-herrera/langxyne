// The node: items the check_xy32 programs import, declared as far as they use them, so their type
// check needs no @types/node.

declare module "node:fs" {
  export function readFileSync(path: string): Uint8Array<ArrayBuffer>;
  export function writeSync(fd: number, text: string): number;
}

declare module "node:path" {
  export function dirname(path: string): string;
  export function join(...paths: string[]): string;
}

declare module "node:url" {
  export function fileURLToPath(url: string): string;
}

declare module "node:process" {
  const process: { argv: string[]; exitCode: number | undefined };
  export default process;
}

declare module "node:wasi" {
  export class WASI {
    constructor(options: { version: "preview1" });
    getImportObject(): object;
    initialize(instance: object): void;
  }
}

declare module "node:worker_threads" {
  export const isMainThread: boolean;
  export const workerData: unknown;
  export class Worker {
    constructor(filename: string, options: { workerData: unknown; resourceLimits: { stackSizeMb: number } });
    on(event: "error", listener: (error: unknown) => void): this;
  }
}

interface ImportMeta {
  url: string;
}
