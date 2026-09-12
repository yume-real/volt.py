import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:mistralai_client_dart/mistralai_client_dart.dart' hide Role;
import 'package:path/path.dart' as path;
import 'package:http/http.dart' as http;

import '../data.dart' as data;
import '../models/models.dart';
import '../utils/utils.dart';

class Engine {
    static final List<String> _narrationPull = [];

    static bool _print = false;
    static bool _cancel = false;

    static bool get isCanceled => _cancel;

    static void cancelGeneration() {
        _cancel = true;
    }

    static Future<GenerationResult> worldGeneration(String settingSummary) async {
        try {
            stdout.clearScreen();
            print(await Global.currentLocale.getEntry('client.newWorldGenerationStart'));

            final messages = [
                ChatEntry(
                    role: Role.system,
                    content: data.worldGenerationSystemPrompt(),
                ),
                ChatEntry(
                    role: Role.user,
                    content: data.worldGenerationUserPrompt(settingSummary),
                ),
            ];
            
            final result = await _sendRequest(messages, Global.currentConfig.getValueOrDefault(ConfigProperty.aiProviderInUse));
            
            if (result.type == ResultType.error) {
                Logger.createLog('No response from ai while world generation', LogType.warning);

                return GenerationResult(
                    ResultType.error,
                    'No response from ai while world generation'
                );
            }

            if (result.type == ResultType.canceled) {
                return GenerationResult(ResultType.canceled, '');
            }

            final world = World.fromJson(jsonDecode(result.content as String));

            print(await Global.currentLocale.getEntry('client.newWorldGenerationFinish'));

            return GenerationResult(
                ResultType.done,
                world
            );
        } catch (e) {
            Logger.createLog('Unexpected error while generating world with mistral ai -> $e',LogType.warning);

            return GenerationResult(
                ResultType.error,
                e.toString()
            );
        }
    }

    static Future<GenerationResult> generateEventOnPlayerAction(final String playerAction, final World world) async {
        final provider = Global.currentConfig.getValueOrDefault(ConfigProperty.aiProviderInUse);
        
        final playerEventRaw = await _sendRequest([
                ChatEntry(
                    role: Role.system, 
                    content: data.playerActionEventGenerationSystemPrompt()
                ),
                ChatEntry(
                    role: Role.user, 
                    content: data.playerActionEventGenerationUserPrompt( 
                        encodeWithIndent(
                            world.toPlayerActionInfo()
                                ..addEntries([MapEntry(
                                    'playerCommand', playerAction
                                )])
                        )
                    )
                )
            ], 
            provider
        );

        if (playerEventRaw.type == ResultType.error) {
            Logger.createLog('Empty response while generation event on player actions', LogType.warning);

            return GenerationResult(
                ResultType.error, 
                'Empty response while generation event on player actions'
            );
        }

        if (playerEventRaw.type == ResultType.canceled) {
             return GenerationResult(
                ResultType.canceled,
                'canceled'
            );
        }

        final playerEventJson = Map<String, dynamic>.from(jsonDecode(playerEventRaw.content as String));
        await write(path.join(Global.programPath, 'report', 'player_action.json'), content: encodeWithIndent(playerEventJson)); // temp

        if ((playerEventJson['commandType'] as String? ?? '') != 'meta_question' && 
            (playerEventJson['actionScale'] as String? ?? '') != 'none') {

            final localEventRaw = await _sendRequest([
                    ChatEntry(
                        role: Role.system,
                        content: data.localEventGenerationSystemPrompt()
                    ),
                    ChatEntry(
                        role: Role.user,
                        content: data.localEventGenerationUserPrompt(
                            encodeWithIndent(
                                world.toEventInfo()
                                    ..addEntries([
                                        MapEntry(
                                            'playerEvent', playerEventJson
                                        ), MapEntry(
                                            'timePassed', 
                                            world.parseSecondsFromAdvanceTime(
                                                (playerEventJson['stateChanges'] as List<dynamic>? ?? [])
                                                .where((s) => (s as Map<String, dynamic>? ?? {}).containsKey('advanceTime'))
                                                .toList()
                                                .firstOrNull ?? {}
                                            ) ?? 0
                                        )
                                    ])
                            )
                        )
                    )
                ], provider
            );

            if (localEventRaw.type == ResultType.error) {
                Logger.createLog('Empty response while generation local event', LogType.warning);

                return GenerationResult(
                    ResultType.error, 
                    'Empty response while generation local event'
                );
            }

            if (localEventRaw.type == ResultType.canceled) {
                return GenerationResult(
                    ResultType.canceled,
                    'canceled'
                );
            }

            final localEventJson = Map<String, dynamic>.from(jsonDecode(localEventRaw.content as String));
            await write(path.join(Global.programPath, 'report', 'final_event.json'), content: encodeWithIndent(localEventJson)); // temp

            return GenerationResult(
                ResultType.done, 
                {
                    'playerEvent': playerEventJson,
                    'localEvent': localEventJson
                }
            );
        }

        return GenerationResult(
            ResultType.done, 
            {
                'playerEvent': playerEventJson
            }
        );
    }

    static Future<GenerationResult> generateLocalEvent(int timePassed, final World world) async {
        final provider = Global.currentConfig.getValueOrDefault(ConfigProperty.aiProviderInUse);

        final localEvent = await _sendRequest(
            [
                ChatEntry (
                    role: Role.system, 
                    content: data.localEventGenerationSystemPrompt()
                ),
                ChatEntry(
                    role: Role.user, 
                    content: data.localEventGenerationUserPrompt(
                        encodeWithIndent(
                            world.toEventInfo()
                                ..addEntries([
                                    MapEntry(
                                        'timePassed', 
                                        timePassed
                                    )
                                ])
                        )
                    )
                )
            ], 
            provider
        );

        if (localEvent.type == ResultType.error) {
            Logger.createLog('Empty response while generation local event', LogType.warning);

            return GenerationResult(
                ResultType.error,
                'Empty response while generation local event'
            );
        }

        if (localEvent.type == ResultType.canceled) {
            return GenerationResult(
                ResultType.canceled,
                'canceled'
            );
        }

        return localEvent;
    }

    static Future<GenerationResult> generateWorldEvent(final World world) async {
        final provider = Global.currentConfig.getValueOrDefault(ConfigProperty.aiProviderInUse);

        final worldEvent = await _sendRequest(
            [
                ChatEntry (
                    role: Role.system, 
                    content: data.localEventGenerationSystemPrompt()
                ),
                ChatEntry(
                    role: Role.user, 
                    content: data.localEventGenerationUserPrompt(
                        encodeWithIndent(
                            world.toEventInfo()
                        )
                    )
                )
            ], 
            provider
        );

        if (worldEvent.type == ResultType.error) {
            Logger.createLog('Empty response while generation local event', LogType.warning);

            return GenerationResult(
                ResultType.error,
                'Empty response while generation local event'
            );
        }

        if (worldEvent.type == ResultType.canceled) {
            return GenerationResult(
                ResultType.canceled,
                'canceled'
            );
        }

        return worldEvent;
    } 

    static void addNarration(String narration) {
        _narrationPull.add(narration);

        if (!_print) {
            _printNarration();
        }
    }

    static Future<void> _printNarration() async {
        final regex = RegExp(r'^\p{P}$', unicode: true);
        final textSpeed = 1 - (Global.currentConfig.getValueOrDefault(ConfigProperty.textSpeed) as num).toDouble();

        _print = true;

        while (_narrationPull.isNotEmpty) {

            for (final symbol in _narrationPull.first.split('')) {
                stdout.write(symbol);

                if (regex.hasMatch(symbol)) {
                    await Future.delayed(Duration(milliseconds: (400 * textSpeed).toInt()));
                } else {
                    await Future.delayed(Duration(milliseconds: (80 * textSpeed).toInt()));
                }
            }

            _narrationPull.removeAt(0);
        }

        _print = false;
    }

    static Future<GenerationResult> _sendRequest(List<ChatEntry> messages, String provider) async {
        return switch (provider) {
            'mistral' => await _sendRequestToMistalAI(messages),
            
            'custom' => await _sendRequestToCustomProvider(messages),

            _ => GenerationResult(ResultType.error, '')
        };
    }

    static Future<GenerationResult> _sendRequestToMistalAI(List<ChatEntry> messages) async {
        try {
            final client = MistralAIClient(apiKey: Global.currentConfig.getValueOrDefault(ConfigProperty.mistralApiKey));

            final response = client.chatStream(
                request: ChatCompletionRequest(
                    model: Global.currentConfig.getValueOrDefault(ConfigProperty.mistralModelName), 
                    messages: messages.map((m) => m.toMistralChatEntry()).toList(),
                    temperature: Global.currentConfig.getValueOrDefault(ConfigProperty.temperature),
                    responseFormat: ResponseFormat(type: ResponseFormats.jsonObject)
                )
            );

            StringBuffer buffer = StringBuffer();

            await for (final chunk in response) {
                final content = chunk.choices.first.delta.content;

                if (_cancel) {
                    _cancel = false;

                    return GenerationResult(ResultType.canceled, '');
                }

                if (content != null) {
                    buffer.write(content);
                }
            }

            client.endSession();

            final content = buffer.toString();

            if (content.isEmpty) {
                return GenerationResult(ResultType.error, 'error');
            }

            return GenerationResult(ResultType.done, buffer.toString());
        } catch (e) {
            return GenerationResult(
                ResultType.error,
                e.toString()
            );
        }
    }
 
    static Future<GenerationResult> _sendRequestToCustomProvider(List<ChatEntry> messages) async {
        final url = Uri.parse(Global.currentConfig.getValueOrDefault(ConfigProperty.customOpenAICompatibleProviderUrl));

        final client = http.Client();

        try {
            final request = http.Request('POST', url)
                ..headers['Content-Type'] = 'application/json'
                ..headers['Authorization'] = 'Bearer ${Global.currentConfig.getValueOrDefault(ConfigProperty.customOpenAICompatibleApiKey)}'
                ..body = jsonEncode({
                    'model': Global.currentConfig.getValueOrDefault(ConfigProperty.customOpenAICompatibleModel),
                    'temperature': Global.currentConfig.getValueOrDefault(ConfigProperty.temperature),
                    'stream': true,
                    'messages':  messages.map((m) => m.toCustomProviderChatEntry()).toList()
                });

            final response = await client.send(request);

            if (response.statusCode == 200) {
                StringBuffer buffer = StringBuffer();

                await for (final line in response.stream.transform(utf8.decoder).transform(const LineSplitter())) {
                    if (line.startsWith('data: ') && !line.contains('[DONE]')) {
                        final jsonString = line.substring(6); 
                        
                        try {
                            final Map<String, dynamic> parsedChunk = jsonDecode(jsonString);
                            final String? chunkContent = parsedChunk['choices']?[0]?['delta']?['content'];

                            if (_cancel) {
                                break;
                            }
                            
                            if (chunkContent != null) {
                                buffer.write(chunkContent);
                            }
                        } catch (_) {

                        }
                    }
                }

                if (_cancel) {
                    _cancel = false;

                    return GenerationResult(ResultType.canceled, '');
                }

                final content = buffer.toString();

                if (content.isEmpty) {
                    return GenerationResult(ResultType.error, 'empty');
                }

                return GenerationResult(ResultType.done, buffer.toString().trim());
            } else {
                Logger.createLog('Error while using custom provider. err code -> ${response.statusCode}', LogType.warning);

                return GenerationResult(ResultType.error, 'Error while using custom provider. err code -> ${response.statusCode}');
            }
        } catch (e) {
            Logger.createLog('Network errror while using custom provider -> $e', LogType.fatal);

            return GenerationResult(ResultType.error, e.toString());
        } finally {
            client.close();
        }
    }
}