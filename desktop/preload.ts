import { contextBridge, ipcRenderer } from "electron";

contextBridge.exposeInMainWorld("humanizeDesktop", {
  health: () => ipcRenderer.invoke("humanize:health"),
  preferences: () => ipcRenderer.invoke("humanize:preferences"),
  selectEngine: (engine: string) => ipcRenderer.invoke("humanize:select-engine", engine),
  chooseCli: (engine: string) => ipcRenderer.invoke("humanize:choose-cli", engine),
  resetCli: (engine: string) => ipcRenderer.invoke("humanize:reset-cli", engine),
  transform: (input: { text: string; engine: string }) => ipcRenderer.invoke("humanize:transform", input),
  cancel: () => ipcRenderer.invoke("humanize:cancel"),
  openText: () => ipcRenderer.invoke("humanize:open-text"),
  saveText: (input: { text: string; name: string }) => ipcRenderer.invoke("humanize:save-text", input),
  copyText: (text: string) => ipcRenderer.invoke("humanize:copy", text),
  onEvent: (callback: (value: unknown) => void) => {
    const listener = (_event: unknown, data: unknown) => callback(data);
    ipcRenderer.on("humanize:event", listener);
    return () => ipcRenderer.removeListener("humanize:event", listener);
  }
});
