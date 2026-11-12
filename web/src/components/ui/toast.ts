import { createContext, useContext } from "react";

export type ToastKind = "success" | "error";
export type Toast = { id: number; kind: ToastKind; message: string };
export type ShowToast = (kind: ToastKind, message: string) => void;

export const ToastContext = createContext<ShowToast>(() => {});
export const useToast = () => useContext(ToastContext);
