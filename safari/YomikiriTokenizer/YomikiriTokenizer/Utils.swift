//
//  Utils.swift
//  YomikiriTokenizer
//
//  Created by Yoonchae Lee on 8/22/24.
//

import Foundation

/// Returns URL path to directory that all Yomikiri apps share
public func getSharedDirectory() throws -> URL {
    let fm = FileManager.default
    if let dir = fm.containerURL(forSecurityApplicationGroupIdentifier: APP_GROUP_ID) {
        return dir
    }
    // Fallback for sideloaded builds without App Group access
    guard let dir = fm.urls(for: .applicationSupportDirectory, in: .userDomainMask).first else {
        throw YomikiriTokenizerError.CouldNotAccessDirectory
    }
    if !fm.fileExists(atPath: dir.path) {
        try fm.createDirectory(at: dir, withIntermediateDirectories: true)
    }
    return dir
}

/// Returns shared caches directory. It is created if it doesn't exist.
public func getSharedCacheDirectory() throws -> URL {
    var dir = try getSharedDirectory()
    dir = dir.appendingPathComponent("Library")
    dir = dir.appendingPathComponent("Caches")
    if !FileManager.default.fileExists(atPath: dir.path) {
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
    }
    return dir
}
