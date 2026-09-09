import 'dart:io';
import 'dart:convert';
import 'package:path/path.dart' as path;
import 'package:intl/intl.dart';

import 'utils/utils.dart';
import 'user_interface.dart' as ui;
import 'models/models.dart';
import 'engine/engine.dart';

Future<void> menu() async {
    final welcomeText = '1) ${await Global.currentLocale.getEntry('client.runServer')}\n'
        '2) ${await Global.currentLocale.getEntry('client.manageSaves')}\n'        
        '3) ${await Global.currentLocale.getEntry('client.openSettings')}\n'
        '4) ${await Global.currentLocale.getEntry('client.exitGame')}\n\n'
        '${await Global.currentLocale.getEntry('client.actionRequest')} ';

    final action = ui.getInt(1, 4, textToShow: welcomeText, disableExit: true);

    switch (action.$2) {
        case 1:
            World? loadedWorld = await chooseSave();

            if (loadedWorld != null) {
                final isReady = ui.getBool(textToShow: '${await Global.currentLocale.getEntry('client.startGameRequest')} ', disableExit: true);

                if (isReady.$2) {
                    await Global.selfStartWithArgs('--server');
                    await startGame(loadedWorld.savePath);
                }
            }

        break;

        case 2:
            await savesEdit();

        break;    

        case 3:
            await configEdit();

        break;

        case 4:
            exit(0);

        default:
            Logger.createLog('input err', LogType.fatal);
            exit(1);
    }
}

Future<void> savesEdit() async {
    final saveDir = Directory(Global.savesDirectoryPath);

    while (true) {
        stdout.clearScreen();

        StringBuffer buffer = StringBuffer();

        final saveFilePaths = await saveDir.list().map((f) => f.path).where((p) => p.endsWith('.json')).toList();
        final saveFileNames = saveFilePaths.map((p) => path.basenameWithoutExtension(p)).toList();

        if (saveFileNames.isNotEmpty) {
            for (int i = 0; i < saveFileNames.length; i++) {
                final saveName = saveFileNames[i];
                final end = saveName.lastIndexOf('_');

                buffer.writeln('${i + 1}) ${saveName.substring(0, end == -1 ? saveName.length : end)}');
            }

            buffer.write('\n${await Global.currentLocale.getEntry('client.savesEdit_request')}'
            '${await Global.exitHint}: ');

            final input = ui.getInt(1, saveFileNames.length, textToShow: buffer.toString());

            if (!input.$1) {
                return;
            }

            final savePath = saveFilePaths[input.$2 - 1];

            final world = World.fromJson(jsonDecode((await read(savePath)).$2));
            world.savePath = savePath;

            await _worldEdit(world);
        } else {
            buffer.writeln(await Global.currentLocale.getEntry('client.savesEdit_noSaves'));
            buffer.write('\n${await Global.currentLocale.getEntry('client.savesEdit_anyButton')}');

            print(buffer.toString());

            stdin.readLineSync();

            return;
        }
    }
}

Future<void> _worldEdit(World world) async {
    var id = world.id;
    var name = world.name;
    var delete = false;

    var changeWorldInfo = false;

    while (true) {
        stdout.clearScreen();

        StringBuffer buffer = StringBuffer();

        buffer.writeln('1) ${await Global.currentLocale.getEntry('client.worldEdit_idChange')} ($id)');
        buffer.writeln('2) ${await Global.currentLocale.getEntry('client.worldEdit_nameChange')} ($name)');
        buffer.writeln('3) ${await Global.currentLocale.getEntry('client.worldEdit_delete')} ($delete)');
        buffer.writeln('4) ${await Global.currentLocale.getEntry('client.worldEdit_save')} ($changeWorldInfo)');

        buffer.write('\n${await Global.currentLocale.getEntry('client.worldEdit_request')} ${await Global.exitHint}: ');

        final result = ui.getInt(1, 4, textToShow: buffer.toString());

        if (!result.$1) {
            break;
        }

        switch (result.$2) {
            case 1:
                final input = ui.getStringInternally(textToShow: 
                    '${await Global.currentLocale.getEntry('client.worldEdit_currentValue')} $id\n\n'
                    '${await Global.currentLocale.getEntry('client.worldSave_newValue')} ${await Global.exitHint}: ');

                final invalidChars = RegExp(r'[<>:"/\\|?*]');
                final result = input.$2.trim();

                if (!input.$1 || result.isEmpty || invalidChars.hasMatch(result)) {
                    break;
                }
                
                id = result;
            break;

            case 2:
                final input = ui.getStringInternally(textToShow: 
                    '${await Global.currentLocale.getEntry('client.worldEdit_currentValue')} $name\n\n'
                    '${await Global.currentLocale.getEntry('client.worldSave_newValue')} ${await Global.exitHint}: ');

                final result = input.$2.trim();

                if (!input.$1 || result.isEmpty) {
                    break;
                }
                
                name = result;
            break;

            case 3:
                delete = !delete;
            
            case 4:
                changeWorldInfo = !changeWorldInfo;
        }
    } 

    if (changeWorldInfo) {
        final file = File(world.savePath);

        if (await file.exists()) {
            await file.delete();
        }

        if (delete) { 
            return;
        }

        final newWorld = world.toJson();

        newWorld['id'] = id;
        newWorld['name'] = name;

        await write(
            path.join(
                Global.savesDirectoryPath,
                '${id}_${DateFormat('yyyy-MM-dd+HH-mm-ss').format(DateTime.now())}.json'
            ),
            content: encodeWithIndent(newWorld)
        );
    }
}

Future<void> configEdit() async {
    var fields = Global.currentConfig.toJson().map((k, v) => MapEntry(k, v)).entries.toList();

    while (true) {
        stdout.clearScreen();
        
        final formated = await Future.wait(
            fields.map((e) async {
                    final key = ConfigProperty.fromString(e.key);

                    return MapEntry(
                        await key.toFormatedString(), 
                        key.isSecret() ? '' : '(${e.value})'
                    );
                }   
            )
        );

        final StringBuffer buffer = StringBuffer();

        for (int i = 0; i < formated.length; i++) {
            buffer.writeln('${i + 1}) ${formated[i].key} ${formated[i].value}');
        }

        buffer.writeln('${formated.length + 1}) ${await Global.currentLocale.getEntry('client.editConfig_reset')}');
        buffer.writeln('${formated.length + 2}) ${await Global.currentLocale.getEntry('client.editConfig_save')}');

        buffer.write('\n${await Global.currentLocale.getEntry('client.editConfig_request')} '
            '${await Global.exitHint}: ');

        final answer = ui.getInt(1, formated.length + 2, textToShow: buffer.toString());

        if (!answer.$1) {
            return;
        }

        if (answer.$2 == formated.length + 1) {
            final defaultConfig = Config.fromJson({})..repairConfig();
            await defaultConfig.writeConfig();

            fields = defaultConfig.toJson().map((k, v) => MapEntry(k, v)).entries.toList();

            await Global.updateEnvironment();

            continue;
        } else if (answer.$2 == formated.length + 2) {
            final newConfig = Config.fromJson(Map.fromEntries(fields));
            await newConfig.writeConfig();

            await Global.updateEnvironment();

            continue;
        } else {
            final index = answer.$2 - 1;
            final field = fields[index];

            final key = ConfigProperty.fromString(field.key);

            bool exit = false;
            dynamic value;

            switch (key.getType()) {

                case ConfigFieldType.int:
                    final min = key.getMin()!.toInt();
                    final max = key.getMax()!.toInt();

                    final result = ui.getInt(
                        min == -1 ? null : min, 
                        max == -1 ? null : max,
                        textToShow: '${await Global.currentLocale.getEntry('client.configEdit_fieldName')} ${await key.toFormatedString()}\n'
                                    '${await Global.currentLocale.getEntry('client.configEdit_currentValue')} ${field.value}\n'
                                    '${await Global.currentLocale.getEntry('client.configEdit_numFieldMin')} $min\n'
                                    '${await Global.currentLocale.getEntry('client.configEdit_numFieldMax')} $max\n\n'
                                    '${await Global.currentLocale.getEntry('client.configEdit_fieldRequest')} ' 
                                    '${await Global.exitHint}: '
                    );

                    exit = !result.$1;
                    value = result.$2;

                break;

                case ConfigFieldType.one:
                    final min = key.getMin();
                    final max = key.getMax();

                    final result = ui.getDouble(
                        min == -1 ? null : min, 
                        max == -1 ? null : max,
                        textToShow: '${await Global.currentLocale.getEntry('client.configEdit_fieldName')} ${await key.toFormatedString()}\n'
                                    '${await Global.currentLocale.getEntry('client.configEdit_currentValue')} ${field.value}\n'
                                    '${await Global.currentLocale.getEntry('client.configEdit_numFieldMin')} $min\n'
                                    '${await Global.currentLocale.getEntry('client.configEdit_numFieldMax')} $max\n\n'
                                    '${await Global.currentLocale.getEntry('client.configEdit_fieldRequest')} ' 
                                    '${await Global.exitHint}: '
                    );

                    exit = !result.$1;
                    value = result.$2;

                break;

                case ConfigFieldType.double:
                    final min = key.getMin();
                    final max = key.getMax();

                    final result = ui.getDouble(
                        min == -1 ? null : min, 
                        max == -1 ? null : max,
                        textToShow: '${await Global.currentLocale.getEntry('client.configEdit_fieldName')} ${await key.toFormatedString()}\n'
                                    '${await Global.currentLocale.getEntry('client.configEdit_currentValue')} ${field.value}\n'
                                    '${await Global.currentLocale.getEntry('client.configEdit_numFieldMin')} $min\n'
                                    '${await Global.currentLocale.getEntry('client.configEdit_numFieldMax')} $max\n\n'
                                    '${await Global.currentLocale.getEntry('client.configEdit_fieldRequest')} ' 
                                    '${await Global.exitHint}: '
                    );

                    exit = !result.$1;
                    value = result.$2;

                break;

                case ConfigFieldType.string:
                    final result = ui.getStringInternally(textToShow: 
                        '${await Global.currentLocale.getEntry('client.configEdit_fieldName')} ${await key.toFormatedString()}\n'
                        '${await Global.currentLocale.getEntry('client.configEdit_currentValue')} ${field.value}\n'
                        '${await Global.currentLocale.getEntry('client.configEdit_fieldRequest')} ' 
                        '${await Global.exitHint}: '
                    );

                    exit = !result.$1;
                    value = result.$2;

                break;

                case ConfigFieldType.bool:
                    final result = ui.getBool(textToShow: 
                        '${await Global.currentLocale.getEntry('client.configEdit_fieldName')} ${await key.toFormatedString()}\n'
                        '${await Global.currentLocale.getEntry('client.configEdit_currentValue')} ${field.value}\n'
                        '${await Global.currentLocale.getEntry('client.configEdit_fieldRequest')} ' 
                        '${await Global.exitHint} [y/n]: '
                    );

                    exit = !result.$1;
                    value = result.$2;

                break;

                case ConfigFieldType.language:
                    final localeList = await Locale.getLocaleNamesList();

                    StringBuffer buffer = StringBuffer();

                    buffer.writeln('${await Global.currentLocale.getEntry('client.configEdit_fieldName')} ${await key.toFormatedString()}');
                    buffer.writeln('${await Global.currentLocale.getEntry('client.configEdit_currentValue')} ${field.value}\n');

                    for (int i = 0; i < localeList.length; i++) {
                        buffer.writeln('${i + 1}) ${localeList[i]}');
                    }

                    buffer.write('\n${await Global.currentLocale.getEntry('client.configEdit_languageRequest')} ' 
                        '${await Global.exitHint}: ');

                    final result = ui.getInt(1, localeList.length, textToShow: buffer.toString());

                    exit = !result.$1;
                    value = exit ? '' : localeList[result.$2 - 1];

                break;
    
            }

            if (!exit) {
                fields[index] = MapEntry(key.toJsonKey(), value);
            }
        }
    }
}

Future<World?> chooseSave() async {                                                               
    var savesText = '1) ${await Global.currentLocale.getEntry('client.createNewSave')}\n';

    final saveDir = Directory(Global.savesDirectoryPath);
    final saveFilePaths = await saveDir.list()
        .map((s) => s.path)
        .where((p) => p.endsWith('.json'))
        .toList();
    final saveNames = saveFilePaths.map((f) => path.basenameWithoutExtension(f)).toList();

    for (int i = 1; i <= saveNames.length; i++) {
        final saveName = saveNames[i - 1];
        final end = saveName.lastIndexOf('_');
        
        savesText += '${i + 1}) ${saveName.substring(0, end == -1 ? saveName.length : end)}\n';
    }

    savesText += '\n${await Global.currentLocale.getEntry('client.saveIndexRequest')} ';

    final saveIndex = ui.getInt(1, saveNames.length + 1, textToShow: savesText);

    if (!saveIndex.$1) {
        return null;
    }

    if (saveIndex.$2 == 1) {
        final summary = await ui.getStringExternaly(textToShow: '${await Global.currentLocale.getEntry('client.newWorldSummaryRequest')} ');

        if (!summary.$1) {
            return null;
        }

        final worldGeneration = await Engine.worldGeneration(summary.$2);

        if (worldGeneration.type == ResultType.done) {
            final newWorld = worldGeneration.content as World;

            newWorld.savePath = path.join(Global.savesDirectoryPath, '${newWorld.id}_${DateFormat('yyyy-MM-dd+HH-mm-ss').format(DateTime.now())}.json');

            await write(newWorld.savePath, content: encodeWithIndent(newWorld.toJson()));

            return newWorld;
        } else {
            stdout.write('${await Global.currentLocale.getEntry('client.worldGeneration_error')} ');

            stdin.readLineSync();
        }

        return null;
    } else {
        final content = await read(saveFilePaths[saveIndex.$2 - 2]);

        if (!content.$1) {
            return null;
        }

        final load = World.fromJson(jsonDecode(content.$2));

        return load..savePath = saveFilePaths[saveIndex.$2 - 2];
    }
}

Future<void> startGame(String worldSaveFilePath) async {
    stdout.clearScreen();

    final socket = await connectToServer(worldSaveFilePath);

    final world = World.fromJson(jsonDecode((await read(worldSaveFilePath)).$2));

    await gameCycle(
        socket, 
        world.messageHistory
            .where((e) => e.role == Role.user)
            .map((e) => e.content)
            .toList()
    );

    socket.close();
}

Future<void> gameCycle(final WebSocket socket, List<String> messages) async {
    while (true) {
        stdout.clearScreen();

        final buffer = StringBuffer();

        for (final message in messages) {
            buffer.writeln('> $message');
        }

        buffer.writeln('\n1) ${await Global.currentLocale.getEntry('client.inGame_sendPrompt')}');
        buffer.writeln('2) ${await Global.currentLocale.getEntry('client.inGame_cancelPrompt')}');
        buffer.writeln('3) ${await Global.currentLocale.getEntry('client.inGame_revert')}');
        buffer.writeln('4) ${await Global.currentLocale.getEntry('client.inGame_exitGame')}');
        buffer.write('\n${await Global.currentLocale.getEntry('client.inGame_request')}: ');

        final userInput = ui.getInt(1, 4, textToShow: buffer.toString(), disableExit: true);

        switch (userInput.$2) {
            
            case 1: 
                stdout.clearScreen();
                for (final message in messages) {
                    print('> $message');
                }

                final prompt = await ui.getStringExternaly(
                    textToShow: '\n${await Global.currentLocale.getEntry('client.inGame_requestPrompt')} '
                        '${await Global.exitHint}', 
                    clearScreen: false);

                if (!prompt.$1 || prompt.$2.isEmpty) {
                    break;
                }

                messages.add(prompt.$2);
                socket.add(
                    encodeWithIndent(
                        Package(action: 'prompt', content: prompt.$2).toJson()
                    )
                );
            break;

            case 2:
                socket.add(
                    encodeWithIndent(
                        Package(action: 'cancel_prompt', content: '').toJson()
                    )
                );
            break;

            case 3:
                socket.add(
                    encodeWithIndent(
                        Package(action: 'revert', content: '').toJson()
                    )
                );
            break;

            case 4:
                socket.add(
                    encodeWithIndent(
                        Package(action: 'exit', content: '').toJson()
                    )
                );

                await Future.delayed(Duration(milliseconds: 500));
            return;
        }
    }
}

Future<WebSocket> connectToServer(String worldSaveFilePath) async {
    final url = 'ws://127.0.0.1:9999';
    stdout.write(await Global.currentLocale.getEntry('client.connectionPending'));

    while (true) {
        try {
            final socket = await WebSocket.connect(url);

            stdout.clearScreen();
            socket.add(worldSaveFilePath);

            return socket;
        } catch (e) {
            stdout.write('.');

            await Future.delayed(const Duration(seconds: 1));
        }
    }
}