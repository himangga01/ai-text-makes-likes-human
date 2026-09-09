import { contextBridge, ipcRenderer } from "electron";

contextBridge.exposeInMainWorld("humanizeDesktop", {
  health: () => ipcRenderer.invoke("humanize:health"),
  preferences: () => ipcRenderer.invoke("humanize:preferences"),
  selectEngine: (engine: string) => ipcRenderer.invoke("humanize:select-engine", engine),
  selectModel: (input: {engine:string;model:string;effort:string})=>ipcRenderer.invoke('humanize:select-model',input),
  chooseCli: (engine: string) => ipcRenderer.invoke("humanize:choose-cli", engine),
  resetCli: (engine: string) => ipcRenderer.invoke("humanize:reset-cli", engine),
  transform: (input: { text: string; engine: string; settings?: {model:string;effort:string} }) => ipcRenderer.invoke("humanize:transform", input),
  cancel: () => ipcRenderer.invoke("humanize:cancel"),
  openText: () => ipcRenderer.invoke("humanize:open-text"),
  transformDocument: (input: {id:string;token:string;engine:string;settings?:{model:string;effort:string}}) => ipcRenderer.invoke('humanize:transform-document',input),
  closeDocument: (input:{id:string;token:string})=>ipcRenderer.invoke('humanize:close-document',input),
  saveDocument: (input:{id:string;token:string})=>ipcRenderer.invoke('humanize:save-document',input),
  saveText: (input: { text: string; name: string }) => ipcRenderer.invoke("humanize:save-text", input),
  copyText: (text: string) => ipcRenderer.invoke("humanize:copy", text),
  onEvent: (callback: (value: unknown) => void) => {
    const listener = (_event: unknown, data: unknown) => callback(data);
    ipcRenderer.on("humanize:event", listener);
    return () => ipcRenderer.removeListener("humanize:event", listener);
  }
});
