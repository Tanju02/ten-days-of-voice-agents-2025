'use client';

import { Button } from '@/components/livekit/button';

function WhisperwoodIcon() {
  return (
    <div className="relative mb-8 whisperwood-glow">
      {/* Glow halo */}
      <div className="absolute inset-0 flex items-center justify-center">
        <div className="h-32 w-32 rounded-full bg-emerald-500/20 blur-2xl animate-pulse" />
      </div>

      {/* Forest emblem */}
      <div className="relative flex items-center justify-center">
        <div className="h-24 w-24 rounded-full bg-gradient-to-br from-emerald-600 to-teal-600 flex items-center justify-center shadow-[0_0_35px_rgba(34,197,94,0.55)]">
          <span className="text-4xl drop-shadow-md">🌲</span>
        </div>

        {/* Floating magical icons */}
        <div className="absolute -top-3 -right-2 text-2xl firefly">✨</div>
        <div
          className="absolute -bottom-1 -left-3 text-xl firefly"
          style={{ animationDelay: '0.35s' }}
        >
          🍃
        </div>
        <div
          className="absolute top-1 left-10 text-lg firefly"
          style={{ animationDelay: '0.6s' }}
        >
          🔮
        </div>
      </div>
    </div>
  );
}

interface WelcomeViewProps {
  startButtonText: string;
  onStartCall: () => void;
}

export const WelcomeView = ({
  startButtonText,
  onStartCall,
  ref,
}: React.ComponentProps<'div'> & WelcomeViewProps) => {
  return (
    <div
      ref={ref}
      className="min-h-screen bg-whisperwood relative overflow-hidden whisper-fog"
    >
      {/* Firefly ambient particles */}
      <div className="pointer-events-none absolute inset-0 opacity-70">
        <div className="absolute -top-32 -left-20 h-64 w-64 rounded-full bg-emerald-500/25 blur-3xl animate-pulse" />
        <div
          className="absolute top-1/3 -right-24 h-72 w-72 rounded-full bg-lime-400/25 blur-3xl animate-pulse"
          style={{ animationDelay: '0.7s' }}
        />
        <div
          className="absolute bottom-[-5rem] left-1/4 h-64 w-64 rounded-full bg-teal-400/20 blur-3xl animate-pulse"
          style={{ animationDelay: '1.1s' }}
        />
      </div>

      {/* Tiny fireflies */}
      <div className="pointer-events-none absolute inset-0">
        <div className="absolute top-20 left-16 h-1 w-1 rounded-full bg-emerald-200 firefly" />
        <div
          className="absolute top-40 right-24 h-1.5 w-1.5 rounded-full bg-lime-300 firefly"
          style={{ animationDelay: '0.4s' }}
        />
        <div
          className="absolute bottom-28 left-1/3 h-1 w-1 rounded-full bg-teal-200 firefly"
          style={{ animationDelay: '0.9s' }}
        />
      </div>

      <section className="relative z-10 flex flex-col items-center justify-center text-center px-4 py-12">
        <WhisperwoodIcon />

        {/* Heading */}
        <div className="mb-4">
          <div className="text-xs md:text-sm uppercase tracking-[0.25em] text-emerald-300/90 mb-2 font-semibold">
            ✨ Enter Whisperwood ✨
          </div>
          <h1 className="text-4xl md:text-5xl font-bold bg-gradient-to-r from-lime-300 via-emerald-300 to-teal-300 bg-clip-text text-transparent mb-3 drop-shadow-[0_0_25px_rgba(34,197,94,0.6)]">
            Forest Game Master
          </h1>
          <p className="text-base md:text-lg text-emerald-100/90">
            A voice-powered magical adventure guided by Alica, the Whisperwood Guardian.
          </p>
        </div>

        {/* Intro card */}
        <div className="bg-gradient-to-br from-emerald-900/40 via-emerald-800/50 to-emerald-900/40 border border-emerald-500/30 rounded-2xl p-6 md:p-7 max-w-2xl mb-6 backdrop-blur-xl shadow-[0_0_35px_rgba(34,197,94,0.45)]">
          <p className="text-emerald-100 text-sm md:text-base leading-relaxed mb-2">
            <span className="text-emerald-300 font-semibold">
              The forest is listening for your voice…
            </span>
          </p>
          <p className="text-emerald-200/90 text-xs md:text-sm leading-relaxed">
            Speak to your AI Game Master and explore the magical Whisperwood forest.
            Discover ancient shrines, meet echo spirits, unlock secrets, and guide your destiny—
            all through your voice.
          </p>
        </div>

        {/* START BUTTON */}
        <div className="mb-8 flex flex-col items-center">
          <Button
            variant="primary"
            size="lg"
            onClick={onStartCall}
            className="w-72 md:w-80 font-semibold text-base md:text-lg bg-gradient-to-r from-emerald-500 via-teal-500 to-lime-500 hover:from-emerald-400 hover:via-teal-400 hover:to-lime-400 border border-emerald-300/60 shadow-[0_0_30px_rgba(34,197,94,0.6)] transition-all duration-300 hover:scale-[1.03] rounded-full"
          >
            {startButtonText || 'Begin Forest Adventure'}
          </Button>
          <p className="text-emerald-300/80 text-[11px] md:text-xs mt-3 italic">
            Click to connect, then say: “Start the story”.
          </p>
        </div>
      </section>
    </div>
  );
};
