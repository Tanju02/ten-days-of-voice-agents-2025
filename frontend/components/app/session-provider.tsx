'use client';

import { createContext, useContext, useMemo } from 'react';
import { RoomContext } from '@livekit/components-react';
import { APP_CONFIG_DEFAULTS, type AppConfig } from '@/app-config';
import { useRoom } from '@/hooks/useRoom';

// ⭐ CHANGE: startSession now receives a name
const SessionContext = createContext<{
  appConfig: AppConfig;
  isSessionActive: boolean;
  startSession: (name: string) => void;
  endSession: () => void;
}>({
  appConfig: APP_CONFIG_DEFAULTS,
  isSessionActive: false,
  startSession: () => {},
  endSession: () => {},
});

interface SessionProviderProps {
  appConfig: AppConfig;
  children: React.ReactNode;
}

export const SessionProvider = ({ appConfig, children }: SessionProviderProps) => {
  // ⭐ CHANGE: useRoom must support passing name → will patch in next file
  const { room, isSessionActive, startSession, endSession } = useRoom(appConfig);

  // ⭐ CHANGE: ensure startSession receives name
  const contextValue = useMemo(
    () => ({
      appConfig,
      isSessionActive,
      startSession: (name: string) => startSession(name),
      endSession,
    }),
    [appConfig, isSessionActive, startSession, endSession]
  );

  return (
    <RoomContext.Provider value={room}>
      <SessionContext.Provider value={contextValue}>
        {children}
      </SessionContext.Provider>
    </RoomContext.Provider>
  );
};

export function useSession() {
  return useContext(SessionContext);
}
