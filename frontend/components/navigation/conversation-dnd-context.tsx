
import { createContext, useContext, type ReactNode } from "react";

export type ActiveDrag = {
  type: "conversation";
  conversationId: string;
  fromProjectId: string | null;
};

export interface ConversationDragContextValue {
  activeDrag: ActiveDrag | null;
  moveInProgress: boolean;
}

const ConversationDragContext = createContext<ConversationDragContextValue | undefined>(undefined);

export function ConversationDragContextProvider({
  value,
  children,
}: {
  value: ConversationDragContextValue;
  children: ReactNode;
}) {
  return (
    <ConversationDragContext.Provider value={value}>
      {children}
    </ConversationDragContext.Provider>
  );
}

export function useConversationDragContext(): ConversationDragContextValue {
  const context = useContext(ConversationDragContext);
  if (!context) {
    throw new Error("useConversationDragContext must be used within a ConversationDragContextProvider");
  }
  return context;
}
