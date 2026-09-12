import '../global.dart';
import 'config_field_type.dart';

enum ConfigProperty {
    language,
    exitPhrase,
    logRotation,
    logRotationLimit,
    aiProviderInUse,
    mistralApiKey,
    mistralModelName,
    customOpenAICompatibleProviderUrl,
    customOpenAICompatibleApiKey,
    customOpenAICompatibleModel,
    temperature,
    messageHistorySize,
    worldHistorySize,
    worldEventsSize,
    worldRumorsSize,
    actorMemorySize,
    actorKnowledgeSize,
    textSpeed,
    generateLocalEvents,
    regenerateAttemptCount;

    double? getMin() {
        final type = getType();

        if (type == ConfigFieldType.int || type == ConfigFieldType.one || type == ConfigFieldType.double) {
            switch (this) {
                case logRotationLimit:
                    return 100;

                case messageHistorySize:
                case worldHistorySize:
                case worldEventsSize:
                case worldRumorsSize:
                case actorMemorySize:
                case actorKnowledgeSize:
                    return 1;

                case temperature:
                    return 0.1;

                case textSpeed:
                case regenerateAttemptCount:
                    return 0;

                default:
                    return null;
            }
        } 

        return null;
    }

    double? getMax() {
        final type = getType();

        if (type == ConfigFieldType.int || type == ConfigFieldType.one || type == ConfigFieldType.double) {
            switch (this) {
                case logRotationLimit:
                case messageHistorySize:
                case worldHistorySize:
                case worldEventsSize:
                case worldRumorsSize:
                case actorMemorySize:
                case actorKnowledgeSize:
                case regenerateAttemptCount:
                    return -1;

                case temperature:
                case textSpeed:
                    return 1;

                default:
                    return null;
            }
        } 

        return null;
    }

    ConfigFieldType getType() {
        switch (this) {
            case logRotationLimit:
            case messageHistorySize:
            case worldHistorySize:
            case worldEventsSize:
            case worldRumorsSize:
            case actorMemorySize:
            case actorKnowledgeSize:
            case regenerateAttemptCount:
                return ConfigFieldType.int;

            case temperature:
            case textSpeed:
                return ConfigFieldType.one;

            case logRotation:
            case generateLocalEvents:
                return ConfigFieldType.bool;

            case language:
                return ConfigFieldType.language;

            default:
                return ConfigFieldType.string;
        }
    }

    bool isSecret() {
        return switch (this) {
            mistralApiKey => true,
            customOpenAICompatibleApiKey => true,

            _ => false 
        };
    }

    factory ConfigProperty.fromString(String string) {
        return switch (string.trim()) {
            'language' => language,
            'exitPhrase' => exitPhrase,
            'logRotation' => logRotation,
            'logRotationLimit' => logRotationLimit,
            'aiProviderInUse' => aiProviderInUse,
            'mistralApiKey' => mistralApiKey,
            'mistralModelName' => mistralModelName,
            'customOpenAICompatibleProviderUrl' => customOpenAICompatibleProviderUrl,
            'customOpenAICompatibleApiKey' => customOpenAICompatibleApiKey,
            'customOpenAICompatibleModel' => customOpenAICompatibleModel,
            'temperature' => temperature,
            'messageHistorySize' => messageHistorySize,
            'worldHistorySize' => worldHistorySize,
            'worldEventsSize' => worldEventsSize,
            'worldRumorsSize' => worldRumorsSize,
            'actorMemorySize' => actorMemorySize,
            'actorKnowledgeSize' => actorKnowledgeSize,
            'textSpeed' => textSpeed,
            'generateLocalEvents' => generateLocalEvents,
            'regenerateAttemptCount' => regenerateAttemptCount,
            
            _ => throw UnsupportedError('Unexpected config entry \'$string\'')
        };    
    }

    String toJsonKey() {
        return switch (this) {
            language => 'language',
            exitPhrase => 'exitPhrase',
            logRotation => 'logRotation',
            logRotationLimit => 'logRotationLimit',
            aiProviderInUse => 'aiProviderInUse',
            mistralApiKey => 'mistralApiKey',
            mistralModelName => 'mistralModelName',
            customOpenAICompatibleProviderUrl => 'customOpenAICompatibleProviderUrl',
            customOpenAICompatibleApiKey => 'customOpenAICompatibleApiKey',
            customOpenAICompatibleModel => 'customOpenAICompatibleModel',
            temperature => 'temperature',
            messageHistorySize => 'messageHistorySize',
            worldHistorySize => 'worldHistorySize',
            worldEventsSize => 'worldEventsSize',
            worldRumorsSize => 'worldRumorsSize',
            actorMemorySize => 'actorMemorySize',
            actorKnowledgeSize => 'actorKnowledgeSize',
            textSpeed => 'textSpeed',
            generateLocalEvents => 'generateLocalEvents',
            regenerateAttemptCount => 'regenerateAttemptCount'
        };
    }

    Future<String> toFormatedString() async {
        return switch (this) {
            language => await Global.currentLocale.getEntry('configProperty.language'),
            exitPhrase => await Global.currentLocale.getEntry('configProperty.exitPhrase'),
            logRotation => await Global.currentLocale.getEntry('configProperty.logRotation'),
            logRotationLimit => await Global.currentLocale.getEntry('configProperty.logRotationLimit'),
            aiProviderInUse => await Global.currentLocale.getEntry('configProperty.aiProviderInUse'),
            mistralApiKey => await Global.currentLocale.getEntry('configProperty.mistralApiKey'),
            mistralModelName => await Global.currentLocale.getEntry('configProperty.mistralModelName'),
            customOpenAICompatibleProviderUrl => await Global.currentLocale.getEntry('configProperty.customOpenAICompatibleProviderUrl'),
            customOpenAICompatibleApiKey => await Global.currentLocale.getEntry('configProperty.customOpenAICompatibleApiKey'),
            customOpenAICompatibleModel => await Global.currentLocale.getEntry('configProperty.customOpenAICompatibleModel'),
            temperature => await Global.currentLocale.getEntry('configProperty.temperature'),
            messageHistorySize => await Global.currentLocale.getEntry('configProperty.messageHistorySize'),
            worldHistorySize => await Global.currentLocale.getEntry('configProperty.worldHistorySize'),
            worldEventsSize => await Global.currentLocale.getEntry('configProperty.worldEventsSize'),
            worldRumorsSize => await Global.currentLocale.getEntry('configProperty.worldRumorsSize'),
            actorMemorySize => await Global.currentLocale.getEntry('configProperty.actorMemorySize'),
            actorKnowledgeSize => await Global.currentLocale.getEntry('configProperty.actorKnowledgeSize'),
            textSpeed => await Global.currentLocale.getEntry('configProperty.textSpeed'),
            generateLocalEvents => await Global.currentLocale.getEntry('configProperty.generateLocalEvents'),
            regenerateAttemptCount => await Global.currentLocale.getEntry('configProperty.regenerateAttemptCount')
        };
    }
}