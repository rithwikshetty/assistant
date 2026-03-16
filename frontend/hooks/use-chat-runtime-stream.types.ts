import type { Message } from "@/lib/chat/runtime/types";

export type {
  AuthoritativeStreamSnapshot,
  ConnectToStreamArgs,
  InputGateState,
  QueuedTurn,
  RecheckAuthoritativeState,
} from "@/lib/chat/runtime/types";

export type SetMessagesFn = (updater: Message[] | ((prev: Message[]) => Message[])) => void;
