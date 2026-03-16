
import { useState, useRef, useCallback, useEffect } from 'react';

import { getBackendBaseUrl } from '@/lib/utils/backend-url';

interface UseVoiceRecorderProps {
  onTranscription: (text: string) => void;
  onError?: (error: string) => void;
}

type PermissionState = 'granted' | 'denied' | 'prompt' | 'unknown';

export function useVoiceRecorder({ onTranscription, onError }: UseVoiceRecorderProps) {
  const [isRecording, setIsRecording] = useState(false);
  const [isTranscribing, setIsTranscribing] = useState(false);
  const [permissionState, setPermissionState] = useState<PermissionState>('unknown');

  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);
  const transcriptionAbortRef = useRef<AbortController | null>(null);

  const apiBaseUrlRef = useRef<string>(getBackendBaseUrl());

  // Check microphone permission status
  useEffect(() => {
    let permissionStatus: PermissionStatus | null = null;
    const checkPermission = async () => {
      try {
        if ('permissions' in navigator) {
          permissionStatus = await navigator.permissions.query({ name: 'microphone' as PermissionName });
          setPermissionState(permissionStatus.state as PermissionState);

          const handleChange = () => {
            setPermissionState(permissionStatus?.state as PermissionState);
          };

          permissionStatus.addEventListener('change', handleChange);

          return () => {
            permissionStatus?.removeEventListener('change', handleChange);
          };
        }
      } catch (_error) {
        // Permissions API not supported - fallback to 'unknown' state
        setPermissionState('unknown');
      }
      return () => {};
    };

    let removeListener: (() => void) | undefined;
    checkPermission().then((cleanup) => {
      removeListener = cleanup;
    });

    return () => {
      removeListener?.();
      permissionStatus = null;
    };
  }, []);

  const transcribeAudio = useCallback(
    async (audioBlob: Blob) => {
      setIsTranscribing(true);

      const abortController = new AbortController();
      transcriptionAbortRef.current = abortController;

      try {
        const formData = new FormData();
        const typeFragment = audioBlob.type.split('/')[1]?.split(';')[0] ?? '';
        const safeExtension = typeFragment.replace(/[^a-z0-9]/gi, '').toLowerCase() || 'webm';
        formData.append('audio', audioBlob, `recording.${safeExtension}`);

        const response = await fetch(`${apiBaseUrlRef.current}/voice/transcribe`, {
          method: 'POST',
          body: formData,
          signal: abortController.signal,
        });

        if (!response.ok) {
          let message = 'Failed to transcribe audio';
          try {
            const error = await response.json();
            if (typeof error?.detail === 'string') {
              message = error.detail;
            }
          } catch {
            // ignore JSON parse errors and use default message
          }
          throw new Error(message);
        }

        const result = await response.json();
        if (typeof result?.text === 'string') {
          onTranscription(result.text);
        } else {
          throw new Error('Transcription succeeded but returned no text.');
        }
      } catch (error: unknown) {
        const err = error as Error;
        if (err?.name === 'AbortError') {
          return;
        }
        if (err?.message !== 'Failed to fetch') {
          onError?.(err?.message || 'Failed to transcribe audio');
        }
      } finally {
        setIsTranscribing(false);
        transcriptionAbortRef.current = null;
        audioChunksRef.current = [];
      }
    },
    [onError, onTranscription],
  );

  const startRecording = useCallback(async () => {
    if (isTranscribing) {
      return;
    }

    // Check if browser supports MediaRecorder
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      onError?.('Browser does not support audio recording');
      return;
    }

    // If we know permission is denied, show a helpful message
    if (permissionState === 'denied') {
      onError?.('Microphone access blocked. Click the lock icon in your address bar to enable it.');
      return;
    }

    try {
      // Start recording - browser will handle permission request
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      
      // Update permission state to granted if successful
      setPermissionState('granted');
      
      // Create MediaRecorder with the stream
      let options: MediaRecorderOptions | undefined;
      try {
        if (typeof MediaRecorder !== 'undefined' && 'isTypeSupported' in MediaRecorder) {
          if (MediaRecorder.isTypeSupported?.('audio/webm')) {
            options = { mimeType: 'audio/webm' };
          }
        }
      } catch {
        options = undefined;
      }

      const mediaRecorder = new MediaRecorder(stream, options);

      mediaRecorderRef.current = mediaRecorder;
      audioChunksRef.current = [];

      mediaRecorder.ondataavailable = (event) => {
        if (event.data.size > 0) {
          audioChunksRef.current.push(event.data);
        }
      };

      mediaRecorder.onstop = async () => {
        const audioBlob = new Blob(audioChunksRef.current, { type: 'audio/webm' });

        // Clean up stream first
        stream.getTracks().forEach(track => track.stop());

        setIsRecording(false);
        mediaRecorderRef.current = null;

        // Only transcribe if we have audio data
        if (audioChunksRef.current.length > 0) {
          await transcribeAudio(audioBlob);
        }
      };

      mediaRecorder.onerror = (_event) => {
        // MediaRecorder error
        onError?.('Recording failed');
        stream.getTracks().forEach(track => track.stop());
        setIsRecording(false);
        mediaRecorderRef.current = null;
        audioChunksRef.current = [];
      };

      mediaRecorder.start();
      setIsRecording(true);
    } catch (error: unknown) {
      // Error starting recording
      setPermissionState('denied');
      
      if (error instanceof DOMException) {
        if (error.name === 'NotAllowedError' || error.name === 'PermissionDeniedError') {
          // Different messages based on browser
          if (navigator.userAgent.includes('Chrome')) {
            onError?.('Microphone blocked. Click the camera icon in the address bar to allow access.');
          } else if (navigator.userAgent.includes('Firefox')) {
            onError?.('Microphone blocked. Click the lock icon in the address bar to allow access.');
          } else {
            onError?.('Microphone access denied. Check your browser settings.');
          }
        } else if (error.name === 'NotFoundError') {
          onError?.('No microphone found. Please connect a microphone and try again.');
        } else if (error.name === 'NotReadableError') {
          onError?.('Microphone is being used by another app. Please close other apps and try again.');
        } else {
          onError?.('Failed to access microphone');
        }
      } else if ((error as Error)?.message?.toLowerCase().includes('permission denied by system')) {
        // macOS specific error
        onError?.('Microphone blocked by system. Go to System Settings > Privacy & Security > Microphone to allow access.');
      } else {
        onError?.('Failed to start recording');
      }
      setIsRecording(false);
    }
  }, [isTranscribing, onError, permissionState, transcribeAudio]);

  const stopRecording = useCallback(() => {
    if (mediaRecorderRef.current && isRecording) {
      mediaRecorderRef.current.stop();
      setIsRecording(false);
    }
  }, [isRecording]);

  useEffect(() => {
    return () => {
      stopRecording();
      transcriptionAbortRef.current?.abort();
      transcriptionAbortRef.current = null;
    };
  }, [stopRecording]);

  return {
    isRecording,
    isTranscribing,
    startRecording,
    stopRecording,
    permissionState,
  };
}
