'use client';

import { AnimatePresence, type HTMLMotionProps, motion } from 'motion/react';
import { type ReceivedChatMessage } from '@livekit/components-react';
import { ChatEntry } from '@/components/livekit/chat-entry';
import clsx from 'clsx';

const MotionContainer = motion.create('div');
const MotionChatEntry = motion.create(ChatEntry);

/* ============================
   Motion Variants (same)
=============================== */
const CONTAINER_MOTION_PROPS = {
  variants: {
    hidden: {
      opacity: 0,
      transition: {
        ease: 'easeOut',
        duration: 0.3,
        staggerChildren: 0.1,
        staggerDirection: -1,
      },
    },
    visible: {
      opacity: 1,
      transition: {
        delay: 0.15,
        ease: 'easeOut',
        duration: 0.35,
        staggerChildren: 0.08,
        staggerDirection: 1,
      },
    },
  },
  initial: 'hidden',
  animate: 'visible',
  exit: 'hidden',
};

const MESSAGE_MOTION_PROPS = {
  variants: {
    hidden: { opacity: 0, translateY: 10 },
    visible: { opacity: 1, translateY: 0 },
  },
};

/* ============================
   Whisperwood ChatTheme Helper
=============================== */
function getBubbleClass(origin: 'local' | 'remote') {
  if (origin === 'local') {
    // Player bubble → soft emerald glow
    return `
      bg-gradient-to-br from-emerald-700/40 to-green-800/30
      border border-emerald-400/25
      shadow-[0_0_12px_rgba(16,185,129,0.35)]
      text-emerald-100
    `;
  }

  // GM bubble (Alica) → magical forest light effect
  return `
    bg-gradient-to-br from-emerald-500/25 via-lime-500/20 to-teal-500/25
    border border-emerald-300/30
    shadow-[0_0_20px_rgba(74,222,128,0.35)]
    text-green-50
  `;
}

function getBubbleName(origin: 'local' | 'remote') {
  return origin === 'local' ? 'You' : 'Alica';
}

interface ChatTranscriptProps {
  hidden?: boolean;
  messages?: ReceivedChatMessage[];
}

export function ChatTranscript({
  hidden = false,
  messages = [],
  ...props
}: ChatTranscriptProps & Omit<HTMLMotionProps<'div'>, 'ref'>) {
  return (
    <AnimatePresence>
      {!hidden && (
        <MotionContainer
          {...CONTAINER_MOTION_PROPS}
          {...props}
          className={clsx(
            'relative w-full h-full overflow-y-auto px-4 py-6 space-y-4',
            'backdrop-blur-xl rounded-xl',
            'bg-gradient-to-b from-emerald-950/40 via-emerald-900/10 to-slate-950/40'
          )}
        >
          {/* Whisperwood ambient fireflies */}
          <div className="pointer-events-none absolute inset-0 overflow-hidden">
            <div className="absolute top-10 left-8 h-1 w-1 rounded-full bg-emerald-300/80 animate-pulse" />
            <div className="absolute top-28 right-16 h-1.5 w-1.5 rounded-full bg-lime-200/80 animate-pulse" style={{ animationDelay: '0.4s' }} />
            <div className="absolute bottom-24 left-1/3 h-1 w-1 rounded-full bg-teal-200/80 animate-pulse" style={{ animationDelay: '0.9s' }} />
            <div className="absolute top-1/2 right-1/3 h-1 w-1 rounded-full bg-green-100/80 animate-pulse" style={{ animationDelay: '1.3s' }} />
          </div>

          {messages.map(({ id, timestamp, from, message, editTimestamp }: ReceivedChatMessage) => {
            const locale = navigator?.language ?? 'en-US';
            const messageOrigin: 'local' | 'remote' = from?.isLocal ? 'local' : 'remote';
            const hasBeenEdited = !!editTimestamp;

            return (
              <div key={id} className="relative z-10">
                <MotionChatEntry
                  {...MESSAGE_MOTION_PROPS}
                  locale={locale}
                  timestamp={timestamp}
                  hasBeenEdited={hasBeenEdited}
                  messageOrigin={messageOrigin}
                  message={
                    <div
                      className={clsx(
                        'whitespace-pre-line rounded-xl px-4 py-3 text-sm leading-relaxed tracking-wide shadow-md',
                        'backdrop-blur-lg',
                        getBubbleClass(messageOrigin)
                      )}
                    >
                      {/* Bubble sender name */}
                      <div className="text-xs opacity-80 mb-1 font-semibold">
                        {getBubbleName(messageOrigin)}
                      </div>

                      {/* Actual message */}
                      <div className="mt-0.5">{message}</div>
                    </div>
                  }
                />
              </div>
            );
          })}
        </MotionContainer>
      )}
    </AnimatePresence>
  );
}
