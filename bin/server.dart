import 'dart:async';
import 'dart:math';
import 'dart:convert';
import 'dart:io';

import 'package:path/path.dart' as path;

import 'utils/utils.dart';
import 'models/models.dart';
import 'engine/engine.dart';

class Server {
    static final List<Package> _pull = []; 

    static late World _world;
    static late World _lastWorldState;

    static Package? _job;
    static int _passedTime = 0;

    static bool _exited = false;

    static Future<void> _processor() async {
        while (!_exited) {
            if (_pull.isNotEmpty) {
                final request = _pull.first;

                switch (request.action) {
                    case 'prompt':
                        if (_job == null) {
                            _prompt(request.content as String);
                        } else {
                            _printJobPendingAlert();
                        }

                        _pull.remove(request);
                    break;

                    case 'cancel_prompt':
                        if (_job != null && _job!.action == 'prompt') {
                            if (!Engine.isCanceled) {
                                Engine.cancelGeneration();

                                Engine.addNarration(
                                    '${await Global.currentLocale.getEntry('client.inGame_promptCancelPending')}\n\n\n'
                                );
                            } else {
                                Engine.addNarration(
                                    '${await Global.currentLocale.getEntry('client.inGame_promptAlreadyCanceled')}\n\n\n'
                                );
                            }
                        } else if (_job != null && _job!.action == 'local_event') {
                            Engine.addNarration(
                                '${await Global.currentLocale.getEntry('client.inGame_cannotCancelLocalEventGeneration')}\n\n\n'
                            );
                        } else if (_job != null && _job!.action == 'world_event') {
                            Engine.addNarration(
                                '${await Global.currentLocale.getEntry('client.inGame_cannotCancelWorldEventGeneration')}\n\n\n'
                            );
                        }
                        else {
                            Engine.addNarration(
                                '${await Global.currentLocale.getEntry('client.inGame_noPromptsPending')}\n\n\n'
                            );
                        }

                        _pull.remove(request);
                    break;

                    case 'revert':
                        if (_job == null) {
                            _revert();
                        } else {
                            _printJobPendingAlert();
                        }

                        _pull.remove(request);
                    break;

                    case 'local_event':
                        if (_job == null) {
                            _localEvent(request.content as int);

                            _pull.remove(request);
                        }   
                    break;

                    case 'world_event':
                        if (_job == null) {
                            _worldEvent();

                            _pull.remove(request);
                        }
                    break;

                    case 'exit':
                        _exited = true;

                    exit(0);
                }
            }
            
            await Future.delayed(Duration(milliseconds: 200));
        }
    }

    static Future<void> _revert() async {
        _job = Package(action: 'revert', content: '');

        _world = World.copy(_lastWorldState);
        await write(_world.savePath, content: encodeWithIndent(_world.toJson()));

        await _printMessageHistory(
            _world.messageHistory
                .where((e) => e.role == Role.assistant)
                .toList()
        );

        _job = null;
    }

    static Future<void> _localEvent(int timePassed) async {
        try {
            _job = Package(action: 'local_event', content: timePassed);

            final regenerateAttempts = Global.currentConfig.getValueOrDefault(ConfigProperty.regenerateAttemptCount);
            _world.advanceTime(timePassed);

            for (int i = 0; i < regenerateAttempts; i++) {
                final eventGeneration = await Engine.generateLocalEvent(timePassed, _world);

                if (eventGeneration.type == ResultType.done) {
                    final event = jsonDecode(eventGeneration.content as String) as Map<String, dynamic>;
                    await write(path.join(Global.programPath, 'report', 'local_event.json'), content: encodeWithIndent(event)); // temp

                    _world.applyChanges(event);

                    final currentNarration = _world.getCurrentNarration();

                    if (currentNarration.isNotEmpty) {
                        _world.addMessageToHistory(
                            role: Role.assistant, 
                            content: '${_world.currentTime.shortTime}: $currentNarration'
                        );

                        await _printMessageHistory(
                            _world.messageHistory
                                .where((e) => e.role == Role.assistant)
                                .toList(),
                            lastSpecial: true
                        );
                    } else {
                        Engine.addNarration(await Global.currentLocale.getEntry('client.inGame_localEventGenerationDone'));
                    }

                    _lastWorldState = World.copy(_world);
                    _world.writeWorld();

                    break;
                } else {
                    Engine.addNarration('${await Global.currentLocale.getEntry('client.inGame_localEventGenerationFailed')}\n');

                    if (regenerateAttempts > 1) {
                        Engine.addNarration('${await Global.currentLocale.getEntry('client.inGame_localEventGenerationRetry')} (${i + 1}/$regenerateAttempts)...\n\n\n');
                    } else {
                        Engine.addNarration('\n\n\n');
                    }
                }
            }

            if (_world.newDay) {
                _pull.add(Package(action: 'world_event', content: ''));
            }
            
            _passedTime = 0;
            _job = null;
        } catch (e, stack) {
            final message = '\n[${await Global.currentLocale.getEntry('client.inGame_generationError')}]: $e -> $stack';
            
            await Logger.createLog(message, LogType.warning);
            print(message);

            _job = null;
        }
    }

     static Future<void> _worldEvent() async {
        try {
            _job = Package(action: 'world_event', content: '');

            final regenerateAttempts = Global.currentConfig.getValueOrDefault(ConfigProperty.regenerateAttemptCount);

            for (int i = 0; i < regenerateAttempts; i++) {
                final eventGeneration = await Engine.generateWorldEvent(_world);

                if (eventGeneration.type == ResultType.done) {
                    final event = jsonDecode(eventGeneration.content as String) as Map<String, dynamic>;
                    await write(path.join(Global.programPath, 'report', 'world_event.json'), content: encodeWithIndent(event)); // temp

                    _world.applyChanges(event);

                    final currentNarration = _world.getCurrentNarration();

                    if (currentNarration.isNotEmpty) {
                        _world.addMessageToHistory(
                            role: Role.assistant, 
                            content: '${_world.currentTime.shortTime}: $currentNarration'
                        );

                        await _printMessageHistory(
                            _world.messageHistory
                                .where((e) => e.role == Role.assistant)
                                .toList(),
                            lastSpecial: true
                        );
                    } else {
                        Engine.addNarration(await Global.currentLocale.getEntry('client.inGame_worldEventGenerationDone'));
                    }

                    _lastWorldState = World.copy(_world);
                    _world.writeWorld();

                    break;
                } else {
                    Engine.addNarration('${await Global.currentLocale.getEntry('client.inGame_worldEventGenerationFailed')}\n');

                    if (regenerateAttempts > 1) {
                        Engine.addNarration('${await Global.currentLocale.getEntry('client.inGame_worldEventGenerationRetry')} (${i + 1}/$regenerateAttempts)...\n\n\n');
                    } else {
                        Engine.addNarration('\n\n\n');
                    }
                }
            }

            _job = null;
        } catch (e, stack) {
            final message = '\n[${await Global.currentLocale.getEntry('client.inGame_generationError')}]: $e -> $stack';
            
            await Logger.createLog(message, LogType.warning);
            print(message);

            _job = null;
        }
    }

    static Future<void> _prompt(String prompt) async {
        try {
            _job = Package(action: 'prompt', content: prompt);

            Engine.addNarration('${await Global.currentLocale.getEntry('client.ingGame_generationPending')}\n\n\n');

            _lastWorldState = World.copy(_world);

            final eventGeneration = await Engine.generateEventOnPlayerAction(prompt, _world);
            
            if (eventGeneration.type == ResultType.done) {
                final event = eventGeneration.content as Map<String, dynamic>;

                final playerEvent = event['playerEvent'] as Map<String, dynamic>? ?? {};
                final localEvent = event['localEvent'] as Map<String, dynamic>? ?? {};

                _world.applyChanges(playerEvent);
                _world.applyChanges(localEvent);

                final currentNarration = _world.getCurrentNarration();

                _world.addMessageToHistory(role: Role.user, content: prompt);

                _world.addMessageToHistory(
                    role: Role.assistant, 
                    content: '${_world.currentTime.shortTime}: $currentNarration'
                );

                _world.writeWorld();

                await _printMessageHistory(
                    _world.messageHistory
                        .where((e) => e.role == Role.assistant)
                        .toList(),
                    lastSpecial: true
                );
            } else if (eventGeneration.type == ResultType.canceled) {
                Engine.addNarration('${await Global.currentLocale.getEntry('client.inGame_generationCanceled')}\n\n\n');
            } else {
                Engine.addNarration('${await Global.currentLocale.getEntry('client.inGame_generationFailed')}\n\n\n');
            }

            if (_world.newDay) {
                _pull.add(Package(action: 'world_event', content: ''));
            }
            
            _passedTime = 0;
            _job = null;
        } catch (e, stack) {
            final message = '\n[${await Global.currentLocale.getEntry('client.inGame_generationError')}]: $e -> $stack';
            
            await Logger.createLog(message, LogType.warning);
            print(message);

            _job = null;
        }
    }

    static Future<void> _printMessageHistory(List<ChatEntry> messages, {bool lastSpecial = false}) async {
        stdout.clearScreen();

        for (int i = 0; i < messages.length; i++) {
            final message = messages[i];

            if (lastSpecial && i + 1 == messages.length) {
                Engine.addNarration('${message.id}. ${message.content}\n\n\n');
            } else {
                stdout.write('${message.id}. ${message.content}\n\n\n');
            }
        }
    }

    static Future<void> _printJobPendingAlert() async {
        if (_job != null) {
            final message = switch (_job!.action) {
                'prompt' => await Global.currentLocale.getEntry('client.inGame_promptPendingAlert'),
                'revert' => await Global.currentLocale.getEntry('client.inGame_revertPendingAlert'),
                'local_event' => await Global.currentLocale.getEntry('client.inGame_localEventPendingAlert'),
                'world_event' => await Global.currentLocale.getEntry('client.inGame_worldEventPendingAlert'),

                _ => '' 
            };

            Engine.addNarration('$message\n\n\n');
        }
    }

    static Future<void> _launch(StreamIterator<dynamic> iterator) async {
        try {
            await _printMessageHistory(
                _world.messageHistory
                    .where((e) => e.role == Role.assistant)
                    .toList()
            );

            _timer();
            _processor();

            while (await iterator.moveNext() && !_exited) {
                final package = Package.fromJson(jsonDecode(iterator.current));

                if (package.action == 'prompt') {
                    if (_job == null) {
                        _pull.add(package);

                        continue;
                    }
                }
                
                _pull.add(package);
            }
        } catch (e) {
            await Logger.createLog('Fatal error in iterator -> $e', LogType.fatal);
        }
    }

    static Future<void> _timer() async {
        if (Global.currentConfig.getValueOrDefault(ConfigProperty.generateLocalEvents)) {
            final rnd = Random();

            while (!_exited) {
                if (_job == null) {
                    _passedTime += 1;

                    if (_passedTime >= 300) {
                        if (_passedTime % 200 == 0) {
                            final chance = 30 + ((_passedTime - 300) / 50).toInt();
                            final random = rnd.nextInt(100) + 1;

                            if (random <= chance) {
                                _pull.add(
                                    Package
                                    (
                                        action: 'local_event', 
                                        content: _passedTime
                                    )
                                );
                            }
                        }
                    }
                }

                await Future.delayed(Duration(seconds: 1));
            }
        }
    }

    static Future<void> setup() async {
        final server = await HttpServer.bind(InternetAddress.anyIPv4, 9999);

        await for (HttpRequest request in server) {
            if (WebSocketTransformer.isUpgradeRequest(request)) {
                final socket = await WebSocketTransformer.upgrade(request);
                print(await Global.currentLocale.getEntry('clientConnected'));

                final iterator = StreamIterator(socket);

                if (await iterator.moveNext()) {
                    final String savePath = iterator.current.toString();

                    _world = World.fromJson(jsonDecode((await read(savePath)).$2));
                    _world.savePath = savePath;

                    _lastWorldState = World.copy(_world);

                    await _launch(iterator);

                    await iterator.cancel();
                    await socket.close();

                    return;
                }
            }
        }
    }
}