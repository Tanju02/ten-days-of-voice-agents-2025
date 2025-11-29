'use client';

import React, { useEffect, useRef, useState } from 'react';
import { motion } from 'motion/react';
import type { AppConfig } from '@/app-config';
import { ChatTranscript } from '@/components/app/chat-transcript';
import { PreConnectMessage } from '@/components/app/preconnect-message';
import { TileLayout } from '@/components/app/tile-layout';
import {
  AgentControlBar,
  type ControlBarControls,
} from '@/components/livekit/agent-control-bar/agent-control-bar';
import { useChatMessages } from '@/hooks/useChatMessages';
import { useConnectionTimeout } from '@/hooks/useConnectionTimout';
import { useDebugMode } from '@/hooks/useDebug';
import { cn } from '@/lib/utils';
import { ScrollArea } from '../livekit/scroll-area/scroll-area';

const MotionBottom = motion.create('div');

const IN_DEVELOPMENT = process.env.NODE_ENV !== 'production';

const BOTTOM_VIEW_MOTION_PROPS = {
  variants: {
    visible: { opacity: 1, translateY: '0%' },
    hidden: { opacity: 0, translateY: '100%' },
  },
  initial: 'hidden',
  animate: 'visible',
  exit: 'hidden',
  transition: {
    duration: 0.3,
    delay: 0.5,
    ease: 'easeOut',
  },
};

interface FadeProps {
  top?: boolean;
  bottom?: boolean;
  className?: string;
}

export function Fade({ top = false, bottom = false, className }: FadeProps) {
  return (
    <div
      className={cn(
        'pointer-events-none h-4',
        top && 'bg-gradient-to-b from-emerald-900/70 to-transparent',
        bottom && 'bg-gradient-to-t from-emerald-900/70 to-transparent',
        className
      )}
    />
  );
}

interface SessionViewProps {
  appConfig: AppConfig;
}

export const SessionView = ({
  appConfig,
  ...props
}: React.ComponentProps<'section'> & SessionViewProps) => {
  useConnectionTimeout(200_000);
  useDebugMode({ enabled: IN_DEVELOPMENT });

  const messages = useChatMessages();
  const [chatOpen, setChatOpen] = useState(false);
  const scrollAreaRef = useRef<HTMLDivElement>(null);

  const controls: ControlBarControls = {
    leave: true,
    microphone: true,
    chat: appConfig.supportsChatInput,
    camera: appConfig.supportsVideoInput,
    screenShare: appConfig.supportsVideoInput,
  };

  /* Auto-scroll on latest message */
  useEffect(() => {
    const lastMessage = messages.at(-1);
    const lastMessageIsLocal = lastMessage?.from?.isLocal === true;
    if (scrollAreaRef.current && lastMessageIsLocal) {
      scrollAreaRef.current.scrollTop = scrollAreaRef.current.scrollHeight;
    }
  }, [messages]);

  return (
    <section
      {...props}
      className={cn(
        'relative z-10 h-full w-full overflow-hidden',
        'bg-gradient-to-br from-gray-950 via-emerald-950 to-gray-950'
      )}
    >
      {/* 🌿 Magical ambient orbs */}
      <div className="pointer-events-none absolute inset-0 opacity-40">
        <div className="absolute -top-24 left-10 h-44 w-44 rounded-full bg-emerald-500/20 blur-3xl animate-pulse" />
        <div
          className="absolute top-1/3 right-10 h-56 w-56 rounded-full bg-teal-400/20 blur-3xl animate-pulse"
          style={{ animationDelay: '0.6s' }}
        />
        <div
          className="absolute bottom-0 left-1/4 h-52 w-52 rounded-full bg-lime-400/20 blur-3xl animate-pulse"
          style={{ animationDelay: '1.1s' }}
        />
      </div>

      {/* ✨ Fireflies */}
      <div className="pointer-events-none absolute inset-0">
        <div className="absolute top-16 left-14 h-1 w-1 rounded-full bg-lime-200 animate-pulse" />
        <div
          className="absolute top-32 right-24 h-1.5 w-1.5 rounded-full bg-emerald-300 animate-pulse"
          style={{ animationDelay: '0.4s' }}
        />
        <div
          className="absolute bottom-28 left-1/3 h-1 w-1 rounded-full bg-teal-300 animate-pulse"
          style={{ animationDelay: '0.9s' }}
        />
        <div
          className="absolute top-1/2 right-1/4 h-1 w-1 rounded-full bg-green-200 animate-pulse"
          style={{ animationDelay: '1.3s' }}
        />
      </div>

      {/* 🌿 Chat Transcript Panel */}
      <div
        className={cn(
          'fixed inset-0 grid grid-cols-1 grid-rows-1 transition-all',
          !chatOpen && 'pointer-events-none'
        )}
      >
        <Fade top className="absolute inset-x-4 top-0 h-40" />

        <ScrollArea
          ref={scrollAreaRef}
          className="px-4 pt-40 pb-[150px] md:px-6 md:pb-[180px]"
        >
          <ChatTranscript
            hidden={!chatOpen}
            messages={messages}
            className="mx-auto max-w-2xl space-y-3 transition-opacity duration-300 ease-out"
          />
        </ScrollArea>
      </div>

      {/* 🎥 Tile Layout */}
      <TileLayout chatOpen={chatOpen} />

      {/* 🌙 Bottom Bar (Controls) */}
      <MotionBottom
        {...BOTTOM_VIEW_MOTION_PROPS}
        className="fixed inset-x-3 bottom-0 z-50 md:inset-x-12"
      >
        {appConfig.isPreConnectBufferEnabled && (
          <PreConnectMessage messages={messages} className="pb-4" />
        )}

        <div className="relative mx-auto max-w-2xl pb-3 md:pb-12 bg-gradient-to-t from-emerald-950/90 via-gray-950/80 to-transparent backdrop-blur-xl rounded-t-xl shadow-[0_0_25px_rgba(34,197,94,0.35)]">
          <Fade bottom className="absolute inset-x-0 top-0 h-4 -translate-y-full" />
          <AgentControlBar controls={controls} onChatOpenChange={setChatOpen} />
        </div>
      </MotionBottom>
    </section>
  );
};
